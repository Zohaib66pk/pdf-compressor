import { upload } from "@vercel/blob/client";

const form = document.querySelector(".compress-form[data-blob-upload='true']");
const fileInput = form?.elements.namedItem("pdf");
const targetInput = form?.elements.namedItem("target_size_mb");
const profileInput = form?.elements.namedItem("profile");
const passwordInput = form?.elements.namedItem("password");
const errorBox = document.getElementById("clientError");
const statusBox = document.getElementById("uploadStatus");
const statusText = document.getElementById("uploadStatusText");
const progressMeter = document.getElementById("uploadProgressMeter");
const submitButton = form?.querySelector("button[type='submit']");

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
      setStatus("Uploading your PDF: 0%", 0);
      const pathname = `uploads/${crypto.randomUUID()}-${safeName(file.name)}`;
      const uploaded = await upload(pathname, file, {
        access: "public",
        handleUploadUrl: "/api/blob-upload",
        contentType: "application/pdf",
        multipart: true,
        clientPayload: JSON.stringify({
          filename: file.name,
          size: file.size,
        }),
        onUploadProgress: ({ percentage }) => {
          const value = Math.round(percentage || 0);
          setStatus(`Uploading your PDF: ${value}%`, value);
        },
      });

      setStatus("Compressing your PDF", 100);
      const response = await fetch("/compress-blob", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          blob_url: uploaded.url,
          blob_pathname: uploaded.pathname,
          filename: file.name,
          profile: profileInput?.value || "max",
          target_size_mb: targetInput?.value || "",
          password: passwordInput?.value || "",
        }),
      });

      const html = await response.text();
      if (!response.ok) {
        document.open();
        document.write(html);
        document.close();
        return;
      }

      document.open();
      document.write(html);
      document.close();
    } catch (error) {
      showError(error instanceof Error ? error.message : "Upload failed. Try again.");
      setBusy(false);
      setStatus("Ready to try again", 0);
    }
  });
}
