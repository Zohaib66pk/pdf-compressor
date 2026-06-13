var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __commonJS = (cb, mod) => function __require() {
  try {
    return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
  } catch (e) {
    throw mod = 0, e;
  }
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// node_modules/is-buffer/index.js
var require_is_buffer = __commonJS({
  "node_modules/is-buffer/index.js"(exports, module) {
    module.exports = function isBuffer2(obj) {
      return obj != null && obj.constructor != null && typeof obj.constructor.isBuffer === "function" && obj.constructor.isBuffer(obj);
    };
  }
});

// node_modules/retry/lib/retry_operation.js
var require_retry_operation = __commonJS({
  "node_modules/retry/lib/retry_operation.js"(exports, module) {
    function RetryOperation(timeouts, options) {
      if (typeof options === "boolean") {
        options = { forever: options };
      }
      this._originalTimeouts = JSON.parse(JSON.stringify(timeouts));
      this._timeouts = timeouts;
      this._options = options || {};
      this._maxRetryTime = options && options.maxRetryTime || Infinity;
      this._fn = null;
      this._errors = [];
      this._attempts = 1;
      this._operationTimeout = null;
      this._operationTimeoutCb = null;
      this._timeout = null;
      this._operationStart = null;
      this._timer = null;
      if (this._options.forever) {
        this._cachedTimeouts = this._timeouts.slice(0);
      }
    }
    module.exports = RetryOperation;
    RetryOperation.prototype.reset = function() {
      this._attempts = 1;
      this._timeouts = this._originalTimeouts.slice(0);
    };
    RetryOperation.prototype.stop = function() {
      if (this._timeout) {
        clearTimeout(this._timeout);
      }
      if (this._timer) {
        clearTimeout(this._timer);
      }
      this._timeouts = [];
      this._cachedTimeouts = null;
    };
    RetryOperation.prototype.retry = function(err) {
      if (this._timeout) {
        clearTimeout(this._timeout);
      }
      if (!err) {
        return false;
      }
      var currentTime = (/* @__PURE__ */ new Date()).getTime();
      if (err && currentTime - this._operationStart >= this._maxRetryTime) {
        this._errors.push(err);
        this._errors.unshift(new Error("RetryOperation timeout occurred"));
        return false;
      }
      this._errors.push(err);
      var timeout = this._timeouts.shift();
      if (timeout === void 0) {
        if (this._cachedTimeouts) {
          this._errors.splice(0, this._errors.length - 1);
          timeout = this._cachedTimeouts.slice(-1);
        } else {
          return false;
        }
      }
      var self = this;
      this._timer = setTimeout(function() {
        self._attempts++;
        if (self._operationTimeoutCb) {
          self._timeout = setTimeout(function() {
            self._operationTimeoutCb(self._attempts);
          }, self._operationTimeout);
          if (self._options.unref) {
            self._timeout.unref();
          }
        }
        self._fn(self._attempts);
      }, timeout);
      if (this._options.unref) {
        this._timer.unref();
      }
      return true;
    };
    RetryOperation.prototype.attempt = function(fn, timeoutOps) {
      this._fn = fn;
      if (timeoutOps) {
        if (timeoutOps.timeout) {
          this._operationTimeout = timeoutOps.timeout;
        }
        if (timeoutOps.cb) {
          this._operationTimeoutCb = timeoutOps.cb;
        }
      }
      var self = this;
      if (this._operationTimeoutCb) {
        this._timeout = setTimeout(function() {
          self._operationTimeoutCb();
        }, self._operationTimeout);
      }
      this._operationStart = (/* @__PURE__ */ new Date()).getTime();
      this._fn(this._attempts);
    };
    RetryOperation.prototype.try = function(fn) {
      console.log("Using RetryOperation.try() is deprecated");
      this.attempt(fn);
    };
    RetryOperation.prototype.start = function(fn) {
      console.log("Using RetryOperation.start() is deprecated");
      this.attempt(fn);
    };
    RetryOperation.prototype.start = RetryOperation.prototype.try;
    RetryOperation.prototype.errors = function() {
      return this._errors;
    };
    RetryOperation.prototype.attempts = function() {
      return this._attempts;
    };
    RetryOperation.prototype.mainError = function() {
      if (this._errors.length === 0) {
        return null;
      }
      var counts = {};
      var mainError = null;
      var mainErrorCount = 0;
      for (var i = 0; i < this._errors.length; i++) {
        var error = this._errors[i];
        var message = error.message;
        var count = (counts[message] || 0) + 1;
        counts[message] = count;
        if (count >= mainErrorCount) {
          mainError = error;
          mainErrorCount = count;
        }
      }
      return mainError;
    };
  }
});

// node_modules/retry/lib/retry.js
var require_retry = __commonJS({
  "node_modules/retry/lib/retry.js"(exports) {
    var RetryOperation = require_retry_operation();
    exports.operation = function(options) {
      var timeouts = exports.timeouts(options);
      return new RetryOperation(timeouts, {
        forever: options && (options.forever || options.retries === Infinity),
        unref: options && options.unref,
        maxRetryTime: options && options.maxRetryTime
      });
    };
    exports.timeouts = function(options) {
      if (options instanceof Array) {
        return [].concat(options);
      }
      var opts = {
        retries: 10,
        factor: 2,
        minTimeout: 1 * 1e3,
        maxTimeout: Infinity,
        randomize: false
      };
      for (var key in options) {
        opts[key] = options[key];
      }
      if (opts.minTimeout > opts.maxTimeout) {
        throw new Error("minTimeout is greater than maxTimeout");
      }
      var timeouts = [];
      for (var i = 0; i < opts.retries; i++) {
        timeouts.push(this.createTimeout(i, opts));
      }
      if (options && options.forever && !timeouts.length) {
        timeouts.push(this.createTimeout(i, opts));
      }
      timeouts.sort(function(a, b) {
        return a - b;
      });
      return timeouts;
    };
    exports.createTimeout = function(attempt, opts) {
      var random = opts.randomize ? Math.random() + 1 : 1;
      var timeout = Math.round(random * Math.max(opts.minTimeout, 1) * Math.pow(opts.factor, attempt));
      timeout = Math.min(timeout, opts.maxTimeout);
      return timeout;
    };
    exports.wrap = function(obj, options, methods) {
      if (options instanceof Array) {
        methods = options;
        options = null;
      }
      if (!methods) {
        methods = [];
        for (var key in obj) {
          if (typeof obj[key] === "function") {
            methods.push(key);
          }
        }
      }
      for (var i = 0; i < methods.length; i++) {
        var method = methods[i];
        var original = obj[method];
        obj[method] = function retryWrapper(original2) {
          var op = exports.operation(options);
          var args = Array.prototype.slice.call(arguments, 1);
          var callback = args.pop();
          args.push(function(err) {
            if (op.retry(err)) {
              return;
            }
            if (err) {
              arguments[0] = op.mainError();
            }
            callback.apply(this, arguments);
          });
          op.attempt(function() {
            original2.apply(obj, args);
          });
        }.bind(obj, original);
        obj[method].options = options;
      }
    };
  }
});

// node_modules/retry/index.js
var require_retry2 = __commonJS({
  "node_modules/retry/index.js"(exports, module) {
    module.exports = require_retry();
  }
});

// node_modules/async-retry/lib/index.js
var require_lib = __commonJS({
  "node_modules/async-retry/lib/index.js"(exports, module) {
    var retrier = require_retry2();
    function retry2(fn, opts) {
      function run(resolve, reject) {
        var options = opts || {};
        var op;
        if (!("randomize" in options)) {
          options.randomize = true;
        }
        op = retrier.operation(options);
        function bail(err) {
          reject(err || new Error("Aborted"));
        }
        function onError(err, num) {
          if (err.bail) {
            bail(err);
            return;
          }
          if (!op.retry(err)) {
            reject(op.mainError());
          } else if (options.onRetry) {
            options.onRetry(err, num);
          }
        }
        function runAttempt(num) {
          var val;
          try {
            val = fn(bail, num);
          } catch (err) {
            onError(err, num);
            return;
          }
          Promise.resolve(val).then(resolve).catch(function catchIt(err) {
            onError(err, num);
          });
        }
        op.attempt(runAttempt);
      }
      return new Promise(run);
    }
    module.exports = retry2;
  }
});

// node_modules/throttleit/index.js
var require_throttleit = __commonJS({
  "node_modules/throttleit/index.js"(exports, module) {
    function throttle3(function_, wait) {
      if (typeof function_ !== "function") {
        throw new TypeError(`Expected the first argument to be a \`function\`, got \`${typeof function_}\`.`);
      }
      let timeoutId;
      let lastCallTime = 0;
      return function throttled(...arguments_) {
        clearTimeout(timeoutId);
        const now = Date.now();
        const timeSinceLastCall = now - lastCallTime;
        const delayForNextCall = wait - timeSinceLastCall;
        if (delayForNextCall <= 0) {
          lastCallTime = now;
          function_.apply(this, arguments_);
        } else {
          timeoutId = setTimeout(() => {
            lastCallTime = Date.now();
            function_.apply(this, arguments_);
          }, delayForNextCall);
        }
      };
    }
    module.exports = throttle3;
  }
});

// node_modules/is-node-process/lib/index.mjs
function isNodeProcess() {
  if (typeof navigator !== "undefined" && navigator.product === "ReactNative") {
    return true;
  }
  if (typeof process !== "undefined") {
    const type = process.type;
    if (type === "renderer" || type === "worker") {
      return false;
    }
    return !!(process.versions && process.versions.node);
  }
  return false;
}

// node_modules/@vercel/blob/dist/chunk-3D2SZ6M2.js
var import_is_buffer = __toESM(require_is_buffer(), 1);

// node_modules/@vercel/blob/dist/stream-browser.js
var Readable = {
  toWeb() {
    throw new Error(
      "Vercel Blob: Sorry, we cannot get a Readable stream in this environment. If you see this message please open an issue here: https://github.com/vercel/storage/ with details on your environment."
    );
  }
};

// node_modules/@vercel/blob/dist/chunk-3D2SZ6M2.js
var import_async_retry = __toESM(require_lib(), 1);

// node_modules/@vercel/blob/dist/undici-browser.js
var fetch2 = globalThis.fetch.bind(globalThis);

// node_modules/@vercel/blob/dist/chunk-3D2SZ6M2.js
var import_throttleit = __toESM(require_throttleit(), 1);
var import_throttleit2 = __toESM(require_throttleit(), 1);
var supportsNewBlobFromArrayBuffer = new Promise((resolve) => {
  try {
    const helloAsArrayBuffer = new Uint8Array([104, 101, 108, 108, 111]);
    const blob = new Blob([helloAsArrayBuffer]);
    blob.text().then((text) => {
      resolve(text === "hello");
    }).catch(() => {
      resolve(false);
    });
  } catch {
    resolve(false);
  }
});
async function toReadableStream(value) {
  if (value instanceof ReadableStream) {
    return value;
  }
  if (value instanceof Blob) {
    return value.stream();
  }
  if (isNodeJsReadableStream(value)) {
    return Readable.toWeb(value);
  }
  let streamValue;
  if (value instanceof ArrayBuffer) {
    streamValue = new Uint8Array(value);
  } else if (isNodeJsBuffer(value)) {
    streamValue = value;
  } else {
    streamValue = stringToUint8Array(value);
  }
  if (await supportsNewBlobFromArrayBuffer) {
    return new Blob([streamValue]).stream();
  }
  return new ReadableStream({
    start(controller) {
      controller.enqueue(streamValue);
      controller.close();
    }
  });
}
function isNodeJsReadableStream(value) {
  return typeof value === "object" && typeof value.pipe === "function" && value.readable && typeof value._read === "function" && // @ts-expect-error _readableState does exists on Readable
  typeof value._readableState === "object";
}
function stringToUint8Array(s) {
  const enc = new TextEncoder();
  return enc.encode(s);
}
function isNodeJsBuffer(value) {
  return (0, import_is_buffer.default)(value);
}
var SYMBOL_FOR_REQ_CONTEXT = /* @__PURE__ */ Symbol.for("@vercel/request-context");
var getContext = () => {
  var _a3, _b2, _c;
  const fromSymbol = globalThis;
  return (_c = (_b2 = (_a3 = fromSymbol[SYMBOL_FOR_REQ_CONTEXT]) == null ? void 0 : _a3.get) == null ? void 0 : _b2.call(_a3)) != null ? _c : {};
};
function readEnv(name) {
  try {
    const value = process.env[name];
    return typeof value === "string" && value.trim() !== "" ? value.trim() : void 0;
  } catch {
    return void 0;
  }
}
function getVercelOidcToken() {
  var _a3;
  const tokenFromContext = (_a3 = getContext().headers) == null ? void 0 : _a3["x-vercel-oidc-token"];
  if (typeof tokenFromContext === "string" && tokenFromContext.trim() !== "") {
    return tokenFromContext.trim();
  }
  return readEnv("VERCEL_OIDC_TOKEN");
}
var parseRegExp = /^((-|\+)?(\d+(?:\.\d+)?)) *(kb|mb|gb|tb|pb)$/i;
var map = {
  b: 1,
  kb: 1 << 10,
  mb: 1 << 20,
  gb: 1 << 30,
  tb: 1024 ** 4,
  pb: 1024 ** 5
};
function bytes(val) {
  if (typeof val === "number" && !Number.isNaN(val)) {
    return val;
  }
  if (typeof val !== "string") {
    return null;
  }
  const results = parseRegExp.exec(val);
  let floatValue;
  let unit = "b";
  if (!results) {
    floatValue = parseInt(val, 10);
  } else {
    const [, res, , , unitMatch] = results;
    if (!res) {
      return null;
    }
    floatValue = parseFloat(res);
    if (unitMatch) {
      unit = unitMatch.toLowerCase();
    }
  }
  if (Number.isNaN(floatValue)) {
    return null;
  }
  return Math.floor(map[unit] * floatValue);
}
var defaultVercelBlobApiUrl = "https://vercel.com/api/blob";
function readEnv2(name) {
  try {
    const value = process.env[name];
    return typeof value === "string" && value.trim() !== "" ? value.trim() : void 0;
  } catch {
    return void 0;
  }
}
function parseStoreIdFromReadWriteToken(token) {
  const [, , , storeId = ""] = token.split("_");
  return storeId;
}
function base64UrlDecodeDelegationSegment(segment) {
  let base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const padding = 4 - base64.length % 4;
  if (padding !== 4) {
    base64 += "=".repeat(padding);
  }
  if (typeof atob === "function") {
    return atob(base64);
  }
  if (typeof Buffer !== "undefined") {
    return Buffer.from(base64, "base64").toString("utf8");
  }
  throw new BlobError("Cannot decode base64: no atob or Buffer available.");
}
function parseStoreIdFromDelegationToken(delegationToken) {
  const dot = delegationToken.indexOf(".");
  if (dot < 0) {
    throw new BlobError("Invalid delegation token format.");
  }
  const payloadSeg = delegationToken.slice(0, dot);
  let parsed;
  try {
    parsed = JSON.parse(base64UrlDecodeDelegationSegment(payloadSeg));
  } catch {
    throw new BlobError("Invalid delegation token payload.");
  }
  if (!parsed.storeId || typeof parsed.storeId !== "string") {
    throw new BlobError("Delegation token payload is missing `storeId`.");
  }
  return normalizeStoreId(parsed.storeId);
}
function normalizeStoreId(storeId) {
  return storeId.startsWith("store_") ? storeId.slice("store_".length) : storeId;
}
function resolveBlobAuth(options) {
  var _a3, _b2;
  if (options == null ? void 0 : options.presignedUrlPayload) {
    const storeId = parseStoreIdFromDelegationToken(
      options.presignedUrlPayload.delegationToken
    );
    return { kind: "presigned", storeId };
  }
  if (options == null ? void 0 : options.token) {
    const storeId = parseStoreIdFromReadWriteToken(options.token);
    return { kind: "readWrite", token: options.token, storeId };
  }
  const manualOidcToken = (_a3 = options == null ? void 0 : options.oidcToken) == null ? void 0 : _a3.trim();
  const oidcToken = manualOidcToken || getVercelOidcToken();
  if (oidcToken) {
    const manualStoreId = (_b2 = options == null ? void 0 : options.storeId) == null ? void 0 : _b2.trim();
    if (manualStoreId) {
      return {
        kind: "oidc",
        token: oidcToken,
        storeId: normalizeStoreId(manualStoreId)
      };
    }
    const blobStoreId = readEnv2("BLOB_STORE_ID");
    if (blobStoreId) {
      return {
        kind: "oidc",
        token: oidcToken,
        storeId: normalizeStoreId(blobStoreId)
      };
    }
    if (manualOidcToken) {
      throw new BlobError(
        "oidcToken was passed, but no storeId was found. Pass a `storeId` option or set `BLOB_STORE_ID` to use OIDC auth"
      );
    }
  }
  const readWrite = readEnv2("BLOB_READ_WRITE_TOKEN");
  if (readWrite) {
    const storeId = parseStoreIdFromReadWriteToken(readWrite);
    return { kind: "readWrite", token: readWrite, storeId };
  }
  throw new BlobError(
    "No blob credentials found. Pass a `token` option, set `BLOB_READ_WRITE_TOKEN`, or use `oidcToken` (or `VERCEL_OIDC_TOKEN`) with `storeId` or `BLOB_STORE_ID`."
  );
}
var BlobError = class extends Error {
  constructor(message) {
    super(`Vercel Blob: ${message}`);
  }
};
function isPlainObject(value) {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return (prototype === null || prototype === Object.prototype || Object.getPrototypeOf(prototype) === null) && !(Symbol.toStringTag in value) && !(Symbol.iterator in value);
}
var disallowedPathnameCharacters = ["//"];
var supportsRequestStreams = (() => {
  if (isNodeProcess()) {
    return true;
  }
  const apiUrl = getApiUrl();
  if (apiUrl.startsWith("http://localhost")) {
    return false;
  }
  let duplexAccessed = false;
  const hasContentType = new Request(getApiUrl(), {
    body: new ReadableStream(),
    method: "POST",
    // @ts-expect-error -- TypeScript doesn't yet have duplex but it's in the spec: https://github.com/microsoft/TypeScript-DOM-lib-generator/pull/1729
    get duplex() {
      duplexAccessed = true;
      return "half";
    }
  }).headers.has("Content-Type");
  return duplexAccessed && !hasContentType;
})();
function getApiUrl(pathname = "") {
  let baseUrl = null;
  try {
    baseUrl = process.env.VERCEL_BLOB_API_URL || process.env.NEXT_PUBLIC_VERCEL_BLOB_API_URL;
  } catch {
  }
  return `${baseUrl || defaultVercelBlobApiUrl}${pathname}`;
}
var TEXT_ENCODER = typeof TextEncoder === "function" ? new TextEncoder() : null;
function computeBodyLength(body) {
  if (!body) {
    return 0;
  }
  if (typeof body === "string") {
    if (TEXT_ENCODER) {
      return TEXT_ENCODER.encode(body).byteLength;
    }
    return new Blob([body]).size;
  }
  if ("byteLength" in body && typeof body.byteLength === "number") {
    return body.byteLength;
  }
  if ("size" in body && typeof body.size === "number") {
    return body.size;
  }
  return 0;
}
var createChunkTransformStream = (chunkSize, onProgress) => {
  let buffer = new Uint8Array(0);
  return new TransformStream({
    transform(chunk, controller) {
      const newBuffer = new Uint8Array(buffer.length + chunk.byteLength);
      newBuffer.set(buffer);
      newBuffer.set(new Uint8Array(chunk), buffer.length);
      buffer = newBuffer;
      while (buffer.length >= chunkSize) {
        const newChunk = buffer.slice(0, chunkSize);
        controller.enqueue(newChunk);
        onProgress == null ? void 0 : onProgress(newChunk.byteLength);
        buffer = buffer.slice(chunkSize);
      }
    },
    flush(controller) {
      if (buffer.length > 0) {
        controller.enqueue(buffer);
        onProgress == null ? void 0 : onProgress(buffer.byteLength);
      }
    }
  });
};
function isReadableStream(value) {
  return globalThis.ReadableStream && // TODO: Can be removed once Node.js 16 is no more required internally
  value instanceof ReadableStream;
}
function isStream(value) {
  if (isReadableStream(value)) {
    return true;
  }
  if (isNodeJsReadableStream(value)) {
    return true;
  }
  return false;
}
var addPresignedParams = (url, presignedUrlPayload) => {
  const urlObj = new URL(url);
  for (const [key, value] of Object.entries(presignedUrlPayload.params)) {
    urlObj.searchParams.set(key, value);
  }
  urlObj.searchParams.set(
    "vercel-blob-delegation",
    presignedUrlPayload.delegationToken
  );
  urlObj.searchParams.set(
    "vercel-blob-signature",
    presignedUrlPayload.signature
  );
  return urlObj.toString();
};
var debugIsActive = false;
var _a;
var _b;
try {
  if (((_a = process.env.DEBUG) == null ? void 0 : _a.includes("blob")) || ((_b = process.env.NEXT_PUBLIC_DEBUG) == null ? void 0 : _b.includes("blob"))) {
    debugIsActive = true;
  }
} catch {
}
function debug(message, ...args) {
  if (debugIsActive) {
    console.debug(`vercel-blob: ${message}`, ...args);
  }
}
var _a2;
var DOMException2 = (_a2 = globalThis.DOMException) != null ? _a2 : (() => {
  try {
    atob("~");
  } catch (err) {
    return Object.getPrototypeOf(err).constructor;
  }
})();
var objectToString = Object.prototype.toString;
var isError = (value) => objectToString.call(value) === "[object Error]";
var errorMessages = /* @__PURE__ */ new Set([
  "network error",
  // Chrome
  "Failed to fetch",
  // Chrome
  "NetworkError when attempting to fetch resource.",
  // Firefox
  "The Internet connection appears to be offline.",
  // Safari 16
  "Load failed",
  // Safari 17+
  "Network request failed",
  // `cross-fetch`
  "fetch failed",
  // Undici (Node.js)
  "terminated"
  // Undici (Node.js)
]);
function isNetworkError(error) {
  const isValid = error && isError(error) && error.name === "TypeError" && typeof error.message === "string";
  if (!isValid) {
    return false;
  }
  if (error.message === "Load failed") {
    return error.stack === void 0;
  }
  return errorMessages.has(error.message);
}
var hasFetch = typeof fetch2 === "function";
var hasFetchWithUploadProgress = hasFetch && supportsRequestStreams;
var CHUNK_SIZE = 64 * 1024;
var blobFetch = async ({
  input,
  init,
  onUploadProgress
}) => {
  debug("using fetch");
  let body;
  if (init.body) {
    if (onUploadProgress) {
      const stream = await toReadableStream(init.body);
      let loaded = 0;
      const chunkTransformStream = createChunkTransformStream(
        CHUNK_SIZE,
        (newLoaded) => {
          loaded += newLoaded;
          onUploadProgress(loaded);
        }
      );
      body = stream.pipeThrough(chunkTransformStream);
    } else {
      body = init.body;
    }
  }
  const duplex = supportsRequestStreams && body && isStream(body) ? "half" : void 0;
  return fetch2(
    input,
    // @ts-expect-error -- Blob and Nodejs Blob are triggering type errors, fine with it
    {
      ...init,
      ...init.body ? { body } : {},
      duplex
    }
  );
};
var hasXhr = typeof XMLHttpRequest !== "undefined";
var blobXhr = async ({
  input,
  init,
  onUploadProgress
}) => {
  debug("using xhr");
  let body = null;
  if (init.body) {
    if (isReadableStream(init.body)) {
      body = await new Response(init.body).blob();
    } else {
      body = init.body;
    }
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(init.method || "GET", input.toString(), true);
    if (onUploadProgress) {
      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) {
          onUploadProgress(event.loaded);
        }
      });
    }
    xhr.onload = () => {
      var _a3;
      if ((_a3 = init.signal) == null ? void 0 : _a3.aborted) {
        reject(new DOMException("The user aborted the request.", "AbortError"));
        return;
      }
      const headers = new Headers();
      const rawHeaders = xhr.getAllResponseHeaders().trim().split(/[\r\n]+/);
      rawHeaders.forEach((line) => {
        const parts = line.split(": ");
        const key = parts.shift();
        const value = parts.join(": ");
        if (key) headers.set(key.toLowerCase(), value);
      });
      const response = new Response(xhr.response, {
        status: xhr.status,
        statusText: xhr.statusText,
        headers
      });
      resolve(response);
    };
    xhr.onerror = () => {
      reject(new TypeError("Network request failed"));
    };
    xhr.ontimeout = () => {
      reject(new TypeError("Network request timed out"));
    };
    xhr.onabort = () => {
      reject(new DOMException("The user aborted a request.", "AbortError"));
    };
    if (init.headers) {
      const headers = new Headers(init.headers);
      headers.forEach((value, key) => {
        xhr.setRequestHeader(key, value);
      });
    }
    if (init.signal) {
      init.signal.addEventListener("abort", () => {
        xhr.abort();
      });
      if (init.signal.aborted) {
        xhr.abort();
        return;
      }
    }
    xhr.send(body);
  });
};
var blobRequest = async ({
  input,
  init,
  onUploadProgress
}) => {
  if (onUploadProgress) {
    if (hasFetchWithUploadProgress) {
      return blobFetch({ input, init, onUploadProgress });
    }
    if (hasXhr) {
      return blobXhr({ input, init, onUploadProgress });
    }
  }
  if (hasFetch) {
    return blobFetch({ input, init });
  }
  if (hasXhr) {
    return blobXhr({ input, init });
  }
  throw new Error("No request implementation available");
};
var MAXIMUM_PATHNAME_LENGTH = 950;
var BlobAccessError = class extends BlobError {
  constructor() {
    super("Access denied, please provide a valid token for this resource.");
  }
};
var BlobOidcEnvironmentNotAllowedError = class extends BlobError {
  constructor(message) {
    super(
      message != null ? message : "OIDC is enabled for this project, but not for this token's environment."
    );
  }
};
var BlobContentTypeNotAllowedError = class extends BlobError {
  constructor(message) {
    super(`Content type mismatch, ${message}.`);
  }
};
var BlobPathnameMismatchError = class extends BlobError {
  constructor(message) {
    super(
      `Pathname mismatch, ${message}. Check the pathname used in upload() or put() matches the one from the client token.`
    );
  }
};
var BlobClientTokenExpiredError = class extends BlobError {
  constructor() {
    super("Client token has expired.");
  }
};
var BlobFileTooLargeError = class extends BlobError {
  constructor(message) {
    super(`File is too large, ${message}.`);
  }
};
var BlobStoreNotFoundError = class extends BlobError {
  constructor() {
    super("This store does not exist.");
  }
};
var BlobStoreSuspendedError = class extends BlobError {
  constructor() {
    super("This store has been suspended.");
  }
};
var BlobUnknownError = class extends BlobError {
  constructor() {
    super("Unknown error, please visit https://vercel.com/help.");
  }
};
var BlobNotFoundError = class extends BlobError {
  constructor() {
    super("The requested blob does not exist");
  }
};
var BlobServiceNotAvailable = class extends BlobError {
  constructor() {
    super("The blob service is currently not available. Please try again.");
  }
};
var BlobServiceRateLimited = class extends BlobError {
  constructor(seconds) {
    super(
      `Too many requests please lower the number of concurrent requests ${seconds ? ` - try again in ${seconds} seconds` : ""}.`
    );
    this.retryAfter = seconds != null ? seconds : 0;
  }
};
var BlobRequestAbortedError = class extends BlobError {
  constructor() {
    super("The request was aborted.");
  }
};
var BlobPreconditionFailedError = class extends BlobError {
  constructor() {
    super("Precondition failed: ETag mismatch.");
  }
};
var BLOB_API_VERSION = 12;
function getApiVersion() {
  let versionOverride = null;
  try {
    versionOverride = process.env.VERCEL_BLOB_API_VERSION_OVERRIDE || process.env.NEXT_PUBLIC_VERCEL_BLOB_API_VERSION_OVERRIDE;
  } catch {
  }
  return `${versionOverride != null ? versionOverride : BLOB_API_VERSION}`;
}
function getRetries() {
  try {
    const retries = process.env.VERCEL_BLOB_RETRIES || "10";
    return parseInt(retries, 10);
  } catch {
    return 10;
  }
}
function createBlobServiceRateLimited(response) {
  const retryAfter = response.headers.get("retry-after");
  return new BlobServiceRateLimited(
    retryAfter ? parseInt(retryAfter, 10) : void 0
  );
}
async function getBlobError(response) {
  var _a3, _b2, _c;
  let code;
  let message;
  try {
    const data = await response.json();
    code = (_b2 = (_a3 = data.error) == null ? void 0 : _a3.code) != null ? _b2 : "unknown_error";
    message = (_c = data.error) == null ? void 0 : _c.message;
  } catch {
    code = "unknown_error";
  }
  if ((message == null ? void 0 : message.includes("contentType")) && message.includes("is not allowed")) {
    code = "content_type_not_allowed";
  }
  if ((message == null ? void 0 : message.includes('"pathname"')) && message.includes("does not match the token payload")) {
    code = "client_token_pathname_mismatch";
  }
  if (message === "Token expired") {
    code = "client_token_expired";
  }
  if (message == null ? void 0 : message.includes("the file length cannot be greater than")) {
    code = "file_too_large";
  }
  if ((message == null ? void 0 : message.startsWith("OIDC is enabled for this project, but not for the")) && message.includes("environment.")) {
    code = "oidc_environment_not_allowed";
  }
  let error;
  switch (code) {
    case "store_suspended":
      error = new BlobStoreSuspendedError();
      break;
    case "forbidden":
      error = new BlobAccessError();
      break;
    case "oidc_environment_not_allowed":
      error = new BlobOidcEnvironmentNotAllowedError(message);
      break;
    case "content_type_not_allowed":
      error = new BlobContentTypeNotAllowedError(message);
      break;
    case "client_token_pathname_mismatch":
      error = new BlobPathnameMismatchError(message);
      break;
    case "client_token_expired":
      error = new BlobClientTokenExpiredError();
      break;
    case "file_too_large":
      error = new BlobFileTooLargeError(message);
      break;
    case "not_found":
      error = new BlobNotFoundError();
      break;
    case "client_token_not_allowed":
      error = new BlobError(
        message != null ? message : "This operation is not available when using a client token. Use a read\u2013write or OIDC token on the server."
      );
      break;
    case "store_not_found":
      error = new BlobStoreNotFoundError();
      break;
    case "bad_request":
      error = new BlobError(message != null ? message : "Bad request");
      break;
    case "service_unavailable":
      error = new BlobServiceNotAvailable();
      break;
    case "rate_limited":
      error = createBlobServiceRateLimited(response);
      break;
    case "precondition_failed":
      error = new BlobPreconditionFailedError();
      break;
    case "unknown_error":
    case "not_allowed":
    default:
      error = new BlobUnknownError();
      break;
  }
  return { code, error };
}
async function requestApi(pathname, init, commandOptions) {
  const apiVersion = getApiVersion();
  const auth = resolveBlobAuth(commandOptions);
  const bearerToken = auth.kind === "presigned" ? void 0 : auth.token;
  const extraHeaders = getProxyThroughAlternativeApiHeaderFromEnv();
  let requestInput = getApiUrl(pathname);
  if (commandOptions == null ? void 0 : commandOptions.presignedUrlPayload) {
    requestInput = addPresignedParams(
      requestInput,
      commandOptions.presignedUrlPayload
    );
  }
  const requestId = `${auth.storeId}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  let retryCount = 0;
  let bodyLength = 0;
  let totalLoaded = 0;
  const sendBodyLength = (commandOptions == null ? void 0 : commandOptions.onUploadProgress) || shouldUseXContentLength();
  if (init.body && // 1. For upload progress we always need to know the total size of the body
  // 2. In development we need the header for put() to work correctly when passing a stream
  sendBodyLength) {
    bodyLength = computeBodyLength(init.body);
  }
  if (commandOptions == null ? void 0 : commandOptions.onUploadProgress) {
    commandOptions.onUploadProgress({
      loaded: 0,
      total: bodyLength,
      percentage: 0
    });
  }
  const apiResponse = await (0, import_async_retry.default)(
    async (bail) => {
      let res;
      try {
        res = await blobRequest({
          input: requestInput,
          init: {
            ...init,
            headers: {
              "x-api-blob-request-id": requestId,
              // Store ID is not encoded in OIDC token, so pass it separately as a header
              "x-vercel-blob-store-id": auth.storeId,
              "x-api-blob-request-attempt": String(retryCount),
              "x-api-version": apiVersion,
              ...sendBodyLength ? { "x-content-length": String(bodyLength) } : {},
              ...bearerToken !== void 0 ? { authorization: `Bearer ${bearerToken}` } : {},
              ...extraHeaders,
              ...init.headers
            }
          },
          onUploadProgress: (commandOptions == null ? void 0 : commandOptions.onUploadProgress) ? (loaded) => {
            var _a3;
            const total = bodyLength !== 0 ? bodyLength : loaded;
            totalLoaded = loaded;
            const percentage = bodyLength > 0 ? Number((loaded / total * 100).toFixed(2)) : 0;
            if (percentage === 100 && bodyLength > 0) {
              return;
            }
            (_a3 = commandOptions.onUploadProgress) == null ? void 0 : _a3.call(commandOptions, {
              loaded,
              // When passing a stream to put(), we have no way to know the total size of the body.
              // Instead of defining total as total?: number we decided to set the total to the currently
              // loaded number. This is not inaccurate and way more practical for DX.
              // Passing down a stream to put() is very rare
              total,
              percentage
            });
          } : void 0
        });
      } catch (error2) {
        if (error2 instanceof DOMException2 && error2.name === "AbortError") {
          bail(new BlobRequestAbortedError());
          return;
        }
        if (isNetworkError(error2)) {
          throw error2;
        }
        if (error2 instanceof TypeError) {
          bail(error2);
          return;
        }
        throw error2;
      }
      if (res.ok) {
        return res;
      }
      const { code, error } = await getBlobError(res);
      if (code === "unknown_error" || code === "service_unavailable" || code === "internal_server_error") {
        throw error;
      }
      bail(error);
    },
    {
      retries: getRetries(),
      onRetry: (error) => {
        if (error instanceof Error) {
          debug(`retrying API request to ${pathname}`, error.message);
        }
        retryCount = retryCount + 1;
      }
    }
  );
  if (!apiResponse) {
    throw new BlobUnknownError();
  }
  if (commandOptions == null ? void 0 : commandOptions.onUploadProgress) {
    commandOptions.onUploadProgress({
      loaded: totalLoaded,
      total: totalLoaded,
      percentage: 100
    });
  }
  return await apiResponse.json();
}
function getProxyThroughAlternativeApiHeaderFromEnv() {
  const extraHeaders = {};
  try {
    if ("VERCEL_BLOB_PROXY_THROUGH_ALTERNATIVE_API" in process.env && process.env.VERCEL_BLOB_PROXY_THROUGH_ALTERNATIVE_API !== void 0) {
      extraHeaders["x-proxy-through-alternative-api"] = process.env.VERCEL_BLOB_PROXY_THROUGH_ALTERNATIVE_API;
    } else if ("NEXT_PUBLIC_VERCEL_BLOB_PROXY_THROUGH_ALTERNATIVE_API" in process.env && process.env.NEXT_PUBLIC_VERCEL_BLOB_PROXY_THROUGH_ALTERNATIVE_API !== void 0) {
      extraHeaders["x-proxy-through-alternative-api"] = process.env.NEXT_PUBLIC_VERCEL_BLOB_PROXY_THROUGH_ALTERNATIVE_API;
    }
  } catch {
  }
  return extraHeaders;
}
function shouldUseXContentLength() {
  try {
    return process.env.VERCEL_BLOB_USE_X_CONTENT_LENGTH === "1";
  } catch {
    return false;
  }
}
var putOptionHeaderMap = {
  cacheControlMaxAge: "x-cache-control-max-age",
  addRandomSuffix: "x-add-random-suffix",
  allowOverwrite: "x-allow-overwrite",
  contentType: "x-content-type",
  access: "x-vercel-blob-access",
  ifMatch: "x-if-match"
};
function createPutHeaders(allowedOptions, options) {
  const headers = {};
  headers[putOptionHeaderMap.access] = options.access;
  if (allowedOptions.includes("contentType") && options.contentType) {
    headers[putOptionHeaderMap.contentType] = options.contentType;
  }
  if (allowedOptions.includes("addRandomSuffix") && options.addRandomSuffix !== void 0) {
    headers[putOptionHeaderMap.addRandomSuffix] = options.addRandomSuffix ? "1" : "0";
  }
  if (allowedOptions.includes("ifMatch") && options.ifMatch) {
    if (options.allowOverwrite === false) {
      throw new BlobError(
        "ifMatch and allowOverwrite: false are contradictory. ifMatch is used for conditional overwrites, which requires allowOverwrite to be true."
      );
    }
    headers[putOptionHeaderMap.ifMatch] = options.ifMatch;
    if (allowedOptions.includes("allowOverwrite") && options.allowOverwrite === void 0) {
      headers[putOptionHeaderMap.allowOverwrite] = "1";
    }
  }
  if (allowedOptions.includes("allowOverwrite") && options.allowOverwrite !== void 0) {
    headers[putOptionHeaderMap.allowOverwrite] = options.allowOverwrite ? "1" : "0";
  }
  if (allowedOptions.includes("cacheControlMaxAge") && options.cacheControlMaxAge !== void 0) {
    headers[putOptionHeaderMap.cacheControlMaxAge] = options.cacheControlMaxAge.toString();
  }
  return headers;
}
async function createPutOptions({
  pathname,
  options,
  extraChecks,
  getToken
}) {
  if (!pathname) {
    throw new BlobError("pathname is required");
  }
  if (pathname.length > MAXIMUM_PATHNAME_LENGTH) {
    throw new BlobError(
      `pathname is too long, maximum length is ${MAXIMUM_PATHNAME_LENGTH}`
    );
  }
  for (const invalidCharacter of disallowedPathnameCharacters) {
    if (pathname.includes(invalidCharacter)) {
      throw new BlobError(
        `pathname cannot contain "${invalidCharacter}", please encode it if needed`
      );
    }
  }
  if (!options) {
    throw new BlobError("missing options, see usage");
  }
  if (options.access !== "public" && options.access !== "private") {
    throw new BlobError(
      'access must be "private" or "public", see https://vercel.com/docs/vercel-blob'
    );
  }
  if (extraChecks) {
    extraChecks(options);
  }
  if (getToken) {
    options.token = await getToken(pathname, options);
  }
  return options;
}
function createCompleteMultipartUploadMethod({ allowedOptions, getToken, extraChecks }) {
  return async (pathname, parts, optionsInput) => {
    const options = await createPutOptions({
      pathname,
      options: optionsInput,
      extraChecks,
      getToken
    });
    const headers = createPutHeaders(allowedOptions, options);
    return completeMultipartUpload({
      uploadId: options.uploadId,
      key: options.key,
      pathname,
      headers,
      options,
      parts
    });
  };
}
async function completeMultipartUpload({
  uploadId,
  key,
  pathname,
  parts,
  headers,
  options
}) {
  const params = new URLSearchParams({ pathname });
  try {
    const response = await requestApi(
      `/mpu?${params.toString()}`,
      {
        method: "POST",
        headers: {
          ...headers,
          "content-type": "application/json",
          "x-mpu-action": "complete",
          "x-mpu-upload-id": uploadId,
          // key can be any utf8 character so we need to encode it as HTTP headers can only be us-ascii
          // https://www.rfc-editor.org/rfc/rfc7230#swection-3.2.4
          "x-mpu-key": encodeURIComponent(key)
        },
        body: JSON.stringify(parts),
        signal: options.abortSignal
      },
      options
    );
    debug("mpu: complete", response);
    return response;
  } catch (error) {
    if (error instanceof TypeError && (error.message === "Failed to fetch" || error.message === "fetch failed")) {
      throw new BlobServiceNotAvailable();
    } else {
      throw error;
    }
  }
}
function createCreateMultipartUploadMethod({ allowedOptions, getToken, extraChecks }) {
  return async (pathname, optionsInput) => {
    const options = await createPutOptions({
      pathname,
      options: optionsInput,
      extraChecks,
      getToken
    });
    const headers = createPutHeaders(allowedOptions, options);
    const createMultipartUploadResponse = await createMultipartUpload(
      pathname,
      headers,
      options
    );
    return {
      key: createMultipartUploadResponse.key,
      uploadId: createMultipartUploadResponse.uploadId
    };
  };
}
async function createMultipartUpload(pathname, headers, options) {
  debug("mpu: create", "pathname:", pathname);
  const params = new URLSearchParams({ pathname });
  try {
    const response = await requestApi(
      `/mpu?${params.toString()}`,
      {
        method: "POST",
        headers: {
          ...headers,
          "x-mpu-action": "create"
        },
        signal: options.abortSignal
      },
      options
    );
    debug("mpu: create", response);
    return response;
  } catch (error) {
    if (error instanceof TypeError && (error.message === "Failed to fetch" || error.message === "fetch failed")) {
      throw new BlobServiceNotAvailable();
    }
    throw error;
  }
}
function createUploadPartMethod({ allowedOptions, getToken, extraChecks }) {
  return async (pathname, body, optionsInput) => {
    const options = await createPutOptions({
      pathname,
      options: optionsInput,
      extraChecks,
      getToken
    });
    const headers = createPutHeaders(allowedOptions, options);
    if (isPlainObject(body)) {
      throw new BlobError(
        "Body must be a string, buffer or stream. You sent a plain JavaScript object, double check what you're trying to upload."
      );
    }
    const result = await uploadPart({
      uploadId: options.uploadId,
      key: options.key,
      pathname,
      part: { blob: body, partNumber: options.partNumber },
      headers,
      options
    });
    return {
      etag: result.etag,
      partNumber: options.partNumber
    };
  };
}
async function uploadPart({
  uploadId,
  key,
  pathname,
  headers,
  options,
  internalAbortController = new AbortController(),
  part
}) {
  var _a3, _b2, _c;
  const params = new URLSearchParams({ pathname });
  const responsePromise = requestApi(
    `/mpu?${params.toString()}`,
    {
      signal: internalAbortController.signal,
      method: "POST",
      headers: {
        ...headers,
        "x-mpu-action": "upload",
        "x-mpu-key": encodeURIComponent(key),
        "x-mpu-upload-id": uploadId,
        "x-mpu-part-number": part.partNumber.toString()
      },
      // weird things between undici types and native fetch types
      body: part.blob
    },
    options
  );
  function handleAbort() {
    internalAbortController.abort();
  }
  if ((_a3 = options.abortSignal) == null ? void 0 : _a3.aborted) {
    handleAbort();
  } else {
    (_b2 = options.abortSignal) == null ? void 0 : _b2.addEventListener("abort", handleAbort);
  }
  const response = await responsePromise;
  (_c = options.abortSignal) == null ? void 0 : _c.removeEventListener("abort", handleAbort);
  return response;
}
var maxConcurrentUploads = typeof window !== "undefined" ? 6 : 8;
var partSizeInBytes = 8 * 1024 * 1024;
var maxBytesInMemory = maxConcurrentUploads * partSizeInBytes * 2;
function uploadAllParts({
  uploadId,
  key,
  pathname,
  stream,
  headers,
  options,
  totalToLoad
}) {
  debug("mpu: upload init", "key:", key);
  const internalAbortController = new AbortController();
  return new Promise((resolve, reject) => {
    const partsToUpload = [];
    const completedParts = [];
    const reader = stream.getReader();
    let activeUploads = 0;
    let reading = false;
    let currentPartNumber = 1;
    let rejected = false;
    let currentBytesInMemory = 0;
    let doneReading = false;
    let bytesSent = 0;
    let arrayBuffers = [];
    let currentPartBytesRead = 0;
    let onUploadProgress;
    const totalLoadedPerPartNumber = {};
    if (options.onUploadProgress) {
      onUploadProgress = (0, import_throttleit.default)(() => {
        var _a3;
        const loaded = Object.values(totalLoadedPerPartNumber).reduce(
          (acc, cur) => {
            return acc + cur;
          },
          0
        );
        const total = totalToLoad || loaded;
        const percentage = totalToLoad > 0 ? Number(((loaded / totalToLoad || loaded) * 100).toFixed(2)) : 0;
        (_a3 = options.onUploadProgress) == null ? void 0 : _a3.call(options, { loaded, total, percentage });
      }, 150);
    }
    read().catch(cancel);
    async function read() {
      debug(
        "mpu: upload read start",
        "activeUploads:",
        activeUploads,
        "currentBytesInMemory:",
        `${bytes(currentBytesInMemory)}/${bytes(maxBytesInMemory)}`,
        "bytesSent:",
        bytes(bytesSent)
      );
      reading = true;
      while (currentBytesInMemory < maxBytesInMemory && !rejected) {
        try {
          const { value, done } = await reader.read();
          if (done) {
            doneReading = true;
            debug("mpu: upload read consumed the whole stream");
            if (arrayBuffers.length > 0) {
              partsToUpload.push({
                partNumber: currentPartNumber++,
                blob: new Blob(arrayBuffers, {
                  type: "application/octet-stream"
                })
              });
              sendParts();
            } else if (activeUploads === 0) {
              reader.releaseLock();
              resolve(completedParts);
            }
            reading = false;
            return;
          }
          currentBytesInMemory += value.byteLength;
          let valueOffset = 0;
          while (valueOffset < value.byteLength) {
            const remainingPartSize = partSizeInBytes - currentPartBytesRead;
            const endOffset = Math.min(
              valueOffset + remainingPartSize,
              value.byteLength
            );
            const chunk = value.slice(valueOffset, endOffset);
            arrayBuffers.push(chunk);
            currentPartBytesRead += chunk.byteLength;
            valueOffset = endOffset;
            if (currentPartBytesRead === partSizeInBytes) {
              partsToUpload.push({
                partNumber: currentPartNumber++,
                blob: new Blob(arrayBuffers, {
                  type: "application/octet-stream"
                })
              });
              arrayBuffers = [];
              currentPartBytesRead = 0;
              sendParts();
            }
          }
        } catch (error) {
          cancel(error);
        }
      }
      debug(
        "mpu: upload read end",
        "activeUploads:",
        activeUploads,
        "currentBytesInMemory:",
        `${bytes(currentBytesInMemory)}/${bytes(maxBytesInMemory)}`,
        "bytesSent:",
        bytes(bytesSent)
      );
      reading = false;
    }
    async function sendPart(part) {
      activeUploads++;
      debug(
        "mpu: upload send part start",
        "partNumber:",
        part.partNumber,
        "size:",
        part.blob.size,
        "activeUploads:",
        activeUploads,
        "currentBytesInMemory:",
        `${bytes(currentBytesInMemory)}/${bytes(maxBytesInMemory)}`,
        "bytesSent:",
        bytes(bytesSent)
      );
      try {
        const uploadProgressForPart = options.onUploadProgress ? (event) => {
          totalLoadedPerPartNumber[part.partNumber] = event.loaded;
          if (onUploadProgress) {
            onUploadProgress();
          }
        } : void 0;
        const completedPart = await uploadPart({
          uploadId,
          key,
          pathname,
          headers,
          options: {
            ...options,
            onUploadProgress: uploadProgressForPart
          },
          internalAbortController,
          part
        });
        debug(
          "mpu: upload send part end",
          "partNumber:",
          part.partNumber,
          "activeUploads",
          activeUploads,
          "currentBytesInMemory:",
          `${bytes(currentBytesInMemory)}/${bytes(maxBytesInMemory)}`,
          "bytesSent:",
          bytes(bytesSent)
        );
        if (rejected) {
          return;
        }
        completedParts.push({
          partNumber: part.partNumber,
          etag: completedPart.etag
        });
        currentBytesInMemory -= part.blob.size;
        activeUploads--;
        bytesSent += part.blob.size;
        if (partsToUpload.length > 0) {
          sendParts();
        }
        if (doneReading) {
          if (activeUploads === 0) {
            reader.releaseLock();
            resolve(completedParts);
          }
          return;
        }
        if (!reading) {
          read().catch(cancel);
        }
      } catch (error) {
        cancel(error);
      }
    }
    function sendParts() {
      if (rejected) {
        return;
      }
      debug(
        "send parts",
        "activeUploads",
        activeUploads,
        "partsToUpload",
        partsToUpload.length
      );
      while (activeUploads < maxConcurrentUploads && partsToUpload.length > 0) {
        const partToSend = partsToUpload.shift();
        if (partToSend) {
          void sendPart(partToSend);
        }
      }
    }
    function cancel(error) {
      if (rejected) {
        return;
      }
      rejected = true;
      internalAbortController.abort();
      reader.releaseLock();
      if (error instanceof TypeError && (error.message === "Failed to fetch" || error.message === "fetch failed")) {
        reject(new BlobServiceNotAvailable());
      } else {
        reject(error);
      }
    }
  });
}
function createCreateMultipartUploaderMethod({ allowedOptions, getToken, extraChecks }) {
  return async (pathname, optionsInput) => {
    const options = await createPutOptions({
      pathname,
      options: optionsInput,
      extraChecks,
      getToken
    });
    const headers = createPutHeaders(allowedOptions, options);
    const createMultipartUploadResponse = await createMultipartUpload(
      pathname,
      headers,
      options
    );
    return {
      key: createMultipartUploadResponse.key,
      uploadId: createMultipartUploadResponse.uploadId,
      async uploadPart(partNumber, body) {
        if (isPlainObject(body)) {
          throw new BlobError(
            "Body must be a string, buffer or stream. You sent a plain JavaScript object, double check what you're trying to upload."
          );
        }
        const result = await uploadPart({
          uploadId: createMultipartUploadResponse.uploadId,
          key: createMultipartUploadResponse.key,
          pathname,
          part: { partNumber, blob: body },
          headers,
          options
        });
        return {
          etag: result.etag,
          partNumber
        };
      },
      async complete(parts) {
        return completeMultipartUpload({
          uploadId: createMultipartUploadResponse.uploadId,
          key: createMultipartUploadResponse.key,
          pathname,
          parts,
          headers,
          options
        });
      }
    };
  };
}
async function uncontrolledMultipartUpload(pathname, body, headers, options) {
  debug("mpu: init", "pathname:", pathname, "headers:", headers);
  const optionsWithoutOnUploadProgress = {
    ...options,
    onUploadProgress: void 0
  };
  if (options.maximumSizeInBytes !== void 0 && !isStream(body) && computeBodyLength(body) > options.maximumSizeInBytes) {
    throw new BlobError(
      `Body size of ${computeBodyLength(body)} bytes exceeds the maximum allowed size of ${options.maximumSizeInBytes} bytes`
    );
  }
  const createMultipartUploadResponse = await createMultipartUpload(
    pathname,
    headers,
    optionsWithoutOnUploadProgress
  );
  const totalToLoad = computeBodyLength(body);
  const stream = await toReadableStream(body);
  const parts = await uploadAllParts({
    uploadId: createMultipartUploadResponse.uploadId,
    key: createMultipartUploadResponse.key,
    pathname,
    // @ts-expect-error ReadableStream<ArrayBuffer | Uint8Array> is compatible at runtime
    stream,
    headers,
    options,
    totalToLoad
  });
  const blob = await completeMultipartUpload({
    uploadId: createMultipartUploadResponse.uploadId,
    key: createMultipartUploadResponse.key,
    pathname,
    parts,
    headers,
    options: optionsWithoutOnUploadProgress
  });
  return blob;
}
function createPutMethod({
  allowedOptions,
  getToken,
  getPresignedUrlPayload,
  extraChecks
}) {
  return async function put2(pathname, body, optionsInput) {
    if (!body) {
      throw new BlobError("body is required");
    }
    if (isPlainObject(body)) {
      throw new BlobError(
        "Body must be a string, buffer or stream. You sent a plain JavaScript object, double check what you're trying to upload."
      );
    }
    const options = await createPutOptions({
      pathname,
      options: optionsInput,
      extraChecks,
      getToken
    });
    const presignedUrlPayload = await (getPresignedUrlPayload == null ? void 0 : getPresignedUrlPayload(
      pathname,
      options
    ));
    const optionsWithPresignedUrlPayload = {
      ...options,
      presignedUrlPayload
    };
    const headers = createPutHeaders(allowedOptions, options);
    if (options.multipart === true) {
      return uncontrolledMultipartUpload(
        pathname,
        body,
        headers,
        optionsWithPresignedUrlPayload
      );
    }
    const onUploadProgress = options.onUploadProgress ? (0, import_throttleit2.default)(options.onUploadProgress, 100) : void 0;
    const params = new URLSearchParams({ pathname });
    const response = await requestApi(
      `/?${params.toString()}`,
      {
        method: "PUT",
        body,
        headers,
        signal: options.abortSignal
      },
      {
        ...optionsWithPresignedUrlPayload,
        onUploadProgress
      }
    );
    return {
      url: response.url,
      downloadUrl: response.downloadUrl,
      pathname: response.pathname,
      contentType: response.contentType,
      contentDisposition: response.contentDisposition,
      etag: response.etag
    };
  };
}
var MAX_PRESIGN_CACHE_CONTROL_MAX_AGE_SECONDS = 365 * 24 * 60 * 60;
var utf8Encoder = new TextEncoder();

// node_modules/@vercel/blob/dist/client.js
function createPutExtraChecks(methodName) {
  return function extraChecks(options) {
    if (!options.token.startsWith("vercel_blob_client_")) {
      throw new BlobError(`${methodName} must be called with a client token`);
    }
    if (
      // @ts-expect-error -- Runtime check for DX.
      options.addRandomSuffix !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.allowOverwrite !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.cacheControlMaxAge !== void 0
    ) {
      throw new BlobError(
        `${methodName} doesn't allow \`addRandomSuffix\`, \`cacheControlMaxAge\` or \`allowOverwrite\`. Configure these options at the server side when generating client tokens.`
      );
    }
  };
}
var put = createPutMethod({
  allowedOptions: ["contentType"],
  extraChecks: createPutExtraChecks("client/`put`")
});
var createMultipartUpload2 = createCreateMultipartUploadMethod({
  allowedOptions: ["contentType"],
  extraChecks: createPutExtraChecks("client/`createMultipartUpload`")
});
var createMultipartUploader = createCreateMultipartUploaderMethod(
  {
    allowedOptions: ["contentType"],
    extraChecks: createPutExtraChecks("client/`createMultipartUpload`")
  }
);
var uploadPart2 = createUploadPartMethod({
  allowedOptions: ["contentType"],
  extraChecks: createPutExtraChecks("client/`multipartUpload`")
});
var completeMultipartUpload2 = createCompleteMultipartUploadMethod(
  {
    allowedOptions: ["contentType"],
    extraChecks: createPutExtraChecks("client/`completeMultipartUpload`")
  }
);
var upload = createPutMethod({
  allowedOptions: ["contentType"],
  extraChecks(options) {
    if (options.handleUploadUrl === void 0) {
      throw new BlobError(
        "client/`upload` requires the 'handleUploadUrl' parameter"
      );
    }
    if (
      // @ts-expect-error -- Runtime check for DX.
      options.addRandomSuffix !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.allowOverwrite !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.cacheControlMaxAge !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.ifMatch !== void 0
    ) {
      throw new BlobError(
        "client/`upload` doesn't allow `addRandomSuffix`, `cacheControlMaxAge`, `allowOverwrite` or `ifMatch`. Configure these options at the server side when generating client tokens."
      );
    }
  },
  async getToken(pathname, options) {
    var _a3, _b2;
    return retrieveClientToken({
      handleUploadUrl: options.handleUploadUrl,
      pathname,
      clientPayload: (_a3 = options.clientPayload) != null ? _a3 : null,
      multipart: (_b2 = options.multipart) != null ? _b2 : false,
      headers: options.headers
    });
  }
});
var uploadPresigned = createPutMethod({
  allowedOptions: ["contentType"],
  extraChecks(options) {
    if (options.handleUploadUrl === void 0) {
      throw new BlobError(
        "client/`upload` requires the 'handleUploadUrl' parameter"
      );
    }
    if (
      // @ts-expect-error -- Runtime check for DX.
      options.addRandomSuffix !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.allowOverwrite !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.cacheControlMaxAge !== void 0 || // @ts-expect-error -- Runtime check for DX.
      options.ifMatch !== void 0
    ) {
      throw new BlobError(
        "client/`uploadPresigned` doesn't allow `addRandomSuffix`, `cacheControlMaxAge`, `allowOverwrite` or `ifMatch`. Configure these options at the server side when generating presigned URLs."
      );
    }
  },
  async getPresignedUrlPayload(pathname, options) {
    var _a3, _b2;
    return retrievePresignedUrlPayload({
      pathname,
      handleUploadUrl: options.handleUploadUrl,
      clientPayload: (_a3 = options.clientPayload) != null ? _a3 : null,
      multipart: (_b2 = options.multipart) != null ? _b2 : false,
      headers: options.headers
    });
  }
});
var EventTypes = {
  generateClientToken: "blob.generate-client-token",
  generatePresignedUrl: "blob.generate-presigned-url",
  uploadCompleted: "blob.upload-completed"
};
async function retrieveClientToken(options) {
  const { handleUploadUrl, pathname } = options;
  const url = isAbsoluteUrl(handleUploadUrl) ? handleUploadUrl : toAbsoluteUrl(handleUploadUrl);
  const event = {
    type: EventTypes.generateClientToken,
    payload: {
      pathname,
      clientPayload: options.clientPayload,
      multipart: options.multipart
    }
  };
  const res = await fetch2(url, {
    method: "POST",
    body: JSON.stringify(event),
    headers: {
      "content-type": "application/json",
      ...options.headers
    },
    signal: options.abortSignal
  });
  if (!res.ok) {
    throw new BlobError("Failed to  retrieve the client token");
  }
  try {
    const { clientToken } = await res.json();
    return clientToken;
  } catch {
    throw new BlobError("Failed to retrieve the client token");
  }
}
async function retrievePresignedUrlPayload(options) {
  const { handleUploadUrl, pathname } = options;
  const url = isAbsoluteUrl(handleUploadUrl) ? handleUploadUrl : toAbsoluteUrl(handleUploadUrl);
  const event = {
    type: EventTypes.generatePresignedUrl,
    payload: {
      pathname,
      clientPayload: options.clientPayload,
      multipart: options.multipart
    }
  };
  const res = await fetch2(url, {
    method: "POST",
    body: JSON.stringify(event),
    headers: {
      "content-type": "application/json",
      ...options.headers
    },
    signal: options.abortSignal
  });
  if (!res.ok) {
    throw new BlobError("Failed to retrieve the presigned URL");
  }
  try {
    const { presignedUrlPayload } = await res.json();
    if (presignedUrlPayload) {
      return presignedUrlPayload;
    }
    throw new BlobError("Missing presignedUrlPayload");
  } catch (error) {
    if (error instanceof BlobError) {
      throw error;
    }
    throw new BlobError("Failed to retrieve the presigned URL");
  }
}
function toAbsoluteUrl(url) {
  return new URL(url, location.href).href;
}
function isAbsoluteUrl(url) {
  try {
    return Boolean(new URL(url));
  } catch {
    return false;
  }
}

// assets/blob-upload-client.js
var form = document.querySelector(".compress-form[data-blob-upload='true']");
var fileInput = form?.elements.namedItem("pdf");
var targetInput = form?.elements.namedItem("target_size_mb");
var profileInput = form?.elements.namedItem("profile");
var passwordInput = form?.elements.namedItem("password");
var errorBox = document.getElementById("clientError");
var statusBox = document.getElementById("uploadStatus");
var statusText = document.getElementById("uploadStatusText");
var progressMeter = document.getElementById("uploadProgressMeter");
var submitButton = form?.querySelector("button[type='submit']");
var steps = {
  uploading: document.getElementById("stepUploading"),
  uploaded: document.getElementById("stepUploaded"),
  compressing: document.getElementById("stepCompressing"),
  ready: document.getElementById("stepReady")
};
var compressionProgressTimer = null;
function showError(message) {
  if (!errorBox) {
    return;
  }
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
  errorBox.setAttribute("tabindex", "-1");
  errorBox.focus();
}
function clearError() {
  if (!errorBox) {
    return;
  }
  errorBox.textContent = "";
  errorBox.classList.add("hidden");
}
function setStatus(message, percent) {
  if (statusBox) {
    statusBox.classList.remove("hidden");
  }
  if (statusText) {
    statusText.textContent = message;
  }
  if (progressMeter) {
    progressMeter.style.width = `${Math.max(0, Math.min(percent, 100))}%`;
  }
}
function setProgress(percent) {
  if (progressMeter) {
    progressMeter.style.width = `${Math.max(0, Math.min(percent, 100))}%`;
  }
}
function setStep(name, state) {
  const step = steps[name];
  if (!step) {
    return;
  }
  step.classList.remove("active", "done");
  if (state) {
    step.classList.add(state);
  }
}
function resetSteps() {
  Object.keys(steps).forEach((name) => setStep(name, ""));
}
function stopCompressionProgress() {
  if (compressionProgressTimer) {
    window.clearInterval(compressionProgressTimer);
    compressionProgressTimer = null;
  }
}
function startCompressionProgress() {
  stopCompressionProgress();
  let progress = 62;
  setProgress(progress);
  compressionProgressTimer = window.setInterval(() => {
    progress = Math.min(progress + 1, 94);
    setProgress(progress);
  }, 900);
}
function setBusy(isBusy) {
  if (!submitButton) {
    return;
  }
  submitButton.disabled = isBusy;
  submitButton.textContent = isBusy ? "Working..." : "Compress PDF";
}
function safeName(name) {
  return name.replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "") || "upload.pdf";
}
if (form) {
  form.addEventListener("submit", async (event) => {
    if (event.defaultPrevented) {
      return;
    }
    event.preventDefault();
    clearError();
    const file = fileInput?.files?.[0];
    const maxUploadBytes = Number(form.dataset.maxUploadBytes || 0);
    if (!file) {
      showError("Choose a PDF file before compressing.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      showError("Uploaded file must be a PDF.");
      return;
    }
    if (maxUploadBytes && file.size > maxUploadBytes) {
      showError("This app supports PDFs up to 100 MB.");
      return;
    }
    setBusy(true);
    try {
      resetSteps();
      setStep("uploading", "active");
      setStatus("Uploading your PDF: 0%", 0);
      const pathname = `uploads/${crypto.randomUUID()}-${safeName(file.name)}`;
      const uploaded = await upload(pathname, file, {
        access: "public",
        handleUploadUrl: "/api/blob-upload",
        contentType: "application/pdf",
        multipart: true,
        clientPayload: JSON.stringify({
          filename: file.name,
          size: file.size
        }),
        onUploadProgress: ({ percentage }) => {
          const value = Math.round(percentage || 0);
          setStatus(`Uploading your PDF: ${value}%`, Math.round(value * 0.55));
        }
      });
      setStep("uploading", "done");
      setStep("uploaded", "done");
      setStep("compressing", "active");
      setStatus("File uploaded. Compression in progress.", 62);
      startCompressionProgress();
      const response = await fetch("/compress-blob", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          blob_url: uploaded.url,
          blob_pathname: uploaded.pathname,
          filename: file.name,
          profile: profileInput?.value || "max",
          target_size_mb: targetInput?.value || "",
          password: passwordInput?.value || ""
        })
      });
      const html = await response.text();
      stopCompressionProgress();
      if (!response.ok) {
        document.open();
        document.write(html);
        document.close();
        return;
      }
      setStep("compressing", "done");
      setStep("ready", "done");
      setStatus("Compression complete. Opening your result.", 100);
      await new Promise((resolve) => window.setTimeout(resolve, 250));
      document.open();
      document.write(html);
      document.close();
    } catch (error) {
      stopCompressionProgress();
      showError(error instanceof Error ? error.message : "Upload failed. Try again.");
      setBusy(false);
      setStatus("Ready to try again", 0);
    }
  });
}
/*! Bundled license information:

is-buffer/index.js:
  (*!
   * Determine if an object is a Buffer
   *
   * @author   Feross Aboukhadijeh <https://feross.org>
   * @license  MIT
   *)

@vercel/blob/dist/chunk-3D2SZ6M2.js:
  (*!
   * bytes
   * Copyright(c) 2012-2014 TJ Holowaychuk
   * Copyright(c) 2015 Jed Watson
   * MIT Licensed
   *)
*/
