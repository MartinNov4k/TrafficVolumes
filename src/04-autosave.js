/* Autosave into the browser so that closing the tab never loses a day's work.
 *
 * IndexedDB holds the whole project, network included, because localStorage is
 * far too small for a real network. localStorage keeps a pointer to the most
 * recent session and, if IndexedDB ever fails, a copy of the typed values as a
 * last resort — the network can always be dropped in again.
 */
(function (TV) {
  'use strict';

  var DB_NAME = 'trafficvolumes';
  var STORE = 'projects';
  var POINTER_KEY = 'tv.lastProject';
  var FALLBACK_KEY = 'tv.fallbackEntries';

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (typeof indexedDB === 'undefined') {
        reject(new Error('IndexedDB není v tomto prohlížeči dostupná.'));
        return;
      }
      var request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = function () {
        var db = request.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id' });
        }
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
      request.onblocked = function () {
        reject(new Error('Databáze je blokovaná jiným otevřeným oknem aplikace.'));
      };
    });
  }

  /** Run one IndexedDB request and resolve with its result. */
  function run(mode, makeRequest) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, mode);
        var request = makeRequest(tx.objectStore(STORE));
        var value;
        request.onsuccess = function () { value = request.result; };
        request.onerror = function () { reject(request.error); };
        tx.oncomplete = function () { db.close(); resolve(value); };
        tx.onerror = function () { db.close(); reject(tx.error); };
        tx.onabort = function () { db.close(); reject(tx.error); };
      });
    });
  }

  function withStorage(work, fallback) {
    try {
      return work(window.localStorage);
    } catch (error) {
      return fallback;
    }
  }

  var Autosave = {
    available: typeof indexedDB !== 'undefined',
    lastSavedAt: null,
    lastError: null,
    _timer: null,

    save: function (project) {
      var self = this;
      var payload = project.toJSON();
      payload.savedAt = new Date().toISOString();
      return run('readwrite', function (store) {
        return store.put(payload);
      }).then(function () {
        self.lastSavedAt = payload.savedAt;
        self.lastError = null;
        withStorage(function (storage) {
          storage.setItem(POINTER_KEY, JSON.stringify({
            id: payload.id,
            name: payload.name,
            savedAt: payload.savedAt,
            total: payload.links.length
          }));
        });
        return payload.savedAt;
      }).catch(function (error) {
        self.lastError = error;
        withStorage(function (storage) {
          storage.setItem(FALLBACK_KEY, JSON.stringify({
            id: payload.id,
            name: payload.name,
            savedAt: payload.savedAt,
            fields: payload.fields,
            entries: payload.entries
          }));
        });
        throw error;
      });
    },

    /** Debounced save; a burst of quick edits collapses into one write. */
    scheduleSave: function (project, onDone) {
      var self = this;
      clearTimeout(this._timer);
      this._timer = setTimeout(function () {
        self.save(project)
          .then(function (at) { if (onDone) onDone(null, at); })
          .catch(function (error) { if (onDone) onDone(error, null); });
      }, 400);
    },

    /** Flush a pending debounced save immediately. */
    flush: function (project) {
      clearTimeout(this._timer);
      return this.save(project);
    },

    list: function () {
      return run('readonly', function (store) {
        return store.getAll();
      }).then(function (rows) {
        return (rows || []).map(function (row) {
          return {
            id: row.id,
            name: row.name,
            savedAt: row.savedAt,
            total: (row.links || []).length,
            filled: Object.keys(row.entries || {}).length
          };
        }).sort(function (a, b) {
          return String(b.savedAt || '').localeCompare(String(a.savedAt || ''));
        });
      }).catch(function () { return []; });
    },

    load: function (id) {
      return run('readonly', function (store) { return store.get(id); })
        .then(function (row) { return row || null; });
    },

    remove: function (id) {
      return run('readwrite', function (store) { return store.delete(id); })
        .then(function () {
          withStorage(function (storage) {
            var raw = storage.getItem(POINTER_KEY);
            if (raw && JSON.parse(raw).id === id) storage.removeItem(POINTER_KEY);
          });
        });
    },

    /** Values kept in localStorage after an IndexedDB failure, if any. */
    fallbackEntries: function () {
      return withStorage(function (storage) {
        var raw = storage.getItem(FALLBACK_KEY);
        return raw ? JSON.parse(raw) : null;
      }, null);
    },

    clearFallback: function () {
      withStorage(function (storage) { storage.removeItem(FALLBACK_KEY); });
    }
  };

  TV.autosave = Autosave;
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));

/* Optional upgrade: keep writing the work straight into a file on disk.
 *
 * Where the File System Access API exists (Chrome and Edge, also from a file://
 * URL), the surveyor picks a destination once and every change is written
 * there. That puts the data in a real file the whole time, not only inside the
 * browser profile. */
(function (TV) {
  'use strict';

  var FileSink = {
    supported: typeof window !== 'undefined' && typeof window.showSaveFilePicker === 'function',
    handle: null,
    fileName: '',
    lastWrittenAt: null,
    lastError: null,
    _timer: null,
    _writing: false,
    _pending: null,

    /** Ask for a destination file. Must be called from a user gesture. */
    choose: function (suggestedName) {
      if (!this.supported) {
        return Promise.reject(new Error(
          'Tento prohlížeč neumí průběžný zápis do souboru. Použijte Chrome nebo Edge, '
          + 'nebo práci ukládejte tlačítkem "Uložit práci (HTML)".'
        ));
      }
      var self = this;
      return window.showSaveFilePicker({
        suggestedName: suggestedName,
        types: [{
          description: 'TrafficVolumes – rozpracovaná práce',
          accept: { 'text/html': ['.html'] }
        }]
      }).then(function (handle) {
        self.handle = handle;
        self.fileName = handle.name;
        self.lastError = null;
        return handle.name;
      });
    },

    forget: function () {
      clearTimeout(this._timer);
      this.handle = null;
      this.fileName = '';
      this.lastWrittenAt = null;
      this._pending = null;
    },

    /** Debounced write; writes are serialised so they cannot interleave. */
    schedule: function (getContent, onDone) {
      if (!this.handle) return;
      var self = this;
      clearTimeout(this._timer);
      this._timer = setTimeout(function () {
        self._write(getContent, onDone);
      }, 1200);
    },

    _write: function (getContent, onDone) {
      var self = this;
      if (this._writing) {
        this._pending = { getContent: getContent, onDone: onDone };
        return;
      }
      this._writing = true;
      Promise.resolve()
        .then(function () { return self.handle.createWritable(); })
        .then(function (writable) {
          return writable.write(getContent()).then(function () { return writable.close(); });
        })
        .then(function () {
          self.lastWrittenAt = new Date().toISOString();
          self.lastError = null;
          if (onDone) onDone(null, self.lastWrittenAt);
        })
        .catch(function (error) {
          self.lastError = error;
          if (onDone) onDone(error, null);
        })
        .then(function () {
          self._writing = false;
          var pending = self._pending;
          self._pending = null;
          if (pending) self._write(pending.getContent, pending.onDone);
        });
    }
  };

  TV.fileSink = FileSink;
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));
