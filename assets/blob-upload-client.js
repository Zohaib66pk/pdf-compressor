import { upload } from "@vercel/blob/client";

const form = document.querySelector(".compress-form[data-blob-upload='true']");
const fileInput = form?.elements.namedItem("pdf");
const targetInput = form?.elements.namedItem("target_size_mb");
const profileInput = form?.elements.namedItem("profile");
const passwordInput = form?.elements.namedItem("password");
const errorBox = document.getElementById("clientError");
const statusBox = document.getElementById("uploadStatus");
const progressMeter = document.getElementById("uploadProgressMeter");
const submitButton = form?.querySelector("button[type='submit']");
const steps = {
  file: document.getElementById("stepFile"),
  compressing: document.getElementById("stepCompressing"),
};
const stepFileText = document.getElementById("stepFileText");
let compressionProgressTimer = null;

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

function showUploadProgress(percent) {
  if (statusBox) {
    statusBox.classList.remove("hidden");
  }
  setProgress(percent);
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

function setFileStepText(message) {
  if (stepFileText) {
    stepFileText.textContent = message;
  }
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
      setFileStepText("File uploading");
      setStep("file", "active");
      showUploadProgress(0);
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
          showUploadProgress(Math.round(value * 0.55));
        },
      });

      setFileStepText("File uploaded");
      setStep("file", "done");
      setStep("compressing", "active");
      showUploadProgress(62);
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
          password: passwordInput?.value || "",
        }),
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
      showUploadProgress(100);
      await new Promise((resolve) => window.setTimeout(resolve, 250));
      document.open();
      document.write(html);
      document.close();
    } catch (error) {
      stopCompressionProgress();
      showError(error instanceof Error ? error.message : "Upload failed. Try again.");
      setBusy(false);
      showUploadProgress(0);
    }
  });
}
