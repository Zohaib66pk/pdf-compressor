import { handleUpload } from "@vercel/blob/client";

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function sendJson(response, status, payload) {
  response.statusCode = status;
  response.setHeader("content-type", "application/json; charset=utf-8");
  response.setHeader("cache-control", "no-store");
  response.end(JSON.stringify(payload));
}

export default async function handler(request, response) {
  if (request.method !== "POST") {
    sendJson(response, 405, { error: "Method not allowed" });
    return;
  }

  try {
    const body = await readJsonBody(request);
    const result = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        const payload = clientPayload ? JSON.parse(clientPayload) : {};
        if (Number(payload.size || 0) > MAX_UPLOAD_BYTES) {
          throw new Error("This app supports PDFs up to 100 MB.");
        }
        if (!String(pathname || "").toLowerCase().endsWith(".pdf")) {
          throw new Error("Uploaded file must be a PDF.");
        }
        return {
          allowedContentTypes: ["application/pdf"],
          maximumSizeInBytes: MAX_UPLOAD_BYTES,
          addRandomSuffix: false,
          cacheControlMaxAge: 60,
          tokenPayload: clientPayload,
        };
      },
      onUploadCompleted: async () => {},
    });
    sendJson(response, 200, result);
  } catch (error) {
    sendJson(response, 400, {
      error: error instanceof Error ? error.message : "Upload could not start.",
    });
  }
}
