const contact = {
  name: "Zan Johan",
  familyName: "Johan",
  givenName: "Zan",
  title: "Digital Systems Architect",
  company: "The Digital Systems Architect",
  phone: "89878714",
  email: "zanj@digi-architect.studio",
  website: "https://digi-architect.studio",
  linkedin: "https://www.linkedin.com/company/the-digital-systems-architect",
  instagram: "https://www.instagram.com/digital.systems.architect",
  facebook: "https://www.facebook.com/share/17tceLy88Z/?mibextid=wwXIfr",
  cardUrl: "https://digi-architect.studio/zan/",
};

const selectors = {
  cardUrl: "[data-card-url]",
  modalCardUrl: "[data-modal-card-url]",
  qrCanvas: "[data-qr-canvas]",
  qrFallback: "[data-qr-fallback]",
  modalQrCanvas: "[data-modal-qr-canvas]",
  modalQrFallback: "[data-modal-qr-fallback]",
  openQr: "[data-open-qr]",
  closeQr: "[data-close-qr]",
  qrModal: "[data-qr-modal]",
  instagramModal: "[data-instagram-modal]",
  openInstagram: "[data-open-instagram]",
  closeInstagram: "[data-close-instagram]",
  saveContact: "[data-save-contact]",
  copyLink: "[data-copy-link]",
  modalCopyLink: "[data-modal-copy-link]",
  copyInstagram: "[data-copy-instagram]",
  websiteLinks: "[data-website-link]",
  whatsappLinks: "[data-whatsapp-link]",
  emailLinks: "[data-email-link]",
  linkedinLinks: "[data-linkedin-link]",
  instagramLinks: "[data-instagram-link]",
  facebookLinks: "[data-facebook-link]",
  toast: "[data-toast]",
};

let lastModalTrigger = null;
let toastTimer = null;

function escapeVCard(value) {
  return String(value)
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function buildVCard() {
  return [
    "BEGIN:VCARD",
    "VERSION:3.0",
    `N:${escapeVCard(contact.familyName)};${escapeVCard(contact.givenName)};;;`,
    `FN:${escapeVCard(contact.name)}`,
    `ORG:${escapeVCard(contact.company)}`,
    `TITLE:${escapeVCard(contact.title)}`,
    `TEL;TYPE=CELL:${escapeVCard(contact.phone)}`,
    `EMAIL;TYPE=INTERNET:${escapeVCard(contact.email)}`,
    `URL:${escapeVCard(contact.website)}`,
    `X-SOCIALPROFILE;TYPE=linkedin:${escapeVCard(contact.linkedin)}`,
    `X-SOCIALPROFILE;TYPE=instagram:${escapeVCard(contact.instagram)}`,
    `X-SOCIALPROFILE;TYPE=facebook:${escapeVCard(contact.facebook)}`,
    "END:VCARD",
  ].join("\r\n");
}

function downloadVCard() {
  const blob = new Blob([buildVCard()], { type: "text/vcard;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = "Zan-Johan.vcf";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function showToast(message) {
  const toast = document.querySelector(selectors.toast);

  if (!toast) return;

  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 1800);
}

async function copyText(value, message) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const tempInput = document.createElement("input");
    tempInput.value = value;
    tempInput.setAttribute("readonly", "");
    document.body.append(tempInput);
    tempInput.select();
    document.execCommand("copy");
    tempInput.remove();
  }

  showToast(message);
}

function setCardUrls() {
  document.querySelectorAll(`${selectors.cardUrl}, ${selectors.modalCardUrl}`).forEach((link) => {
    link.href = contact.cardUrl;
    link.textContent = contact.cardUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
  });
}

function setContactLinks() {
  document.querySelectorAll(selectors.websiteLinks).forEach((link) => {
    link.href = contact.website;
  });
  document.querySelectorAll(selectors.whatsappLinks).forEach((link) => {
    link.href = `https://wa.me/${contact.phone}`;
  });
  document.querySelectorAll(selectors.emailLinks).forEach((link) => {
    link.href = `mailto:${contact.email}`;
  });
  document.querySelectorAll(selectors.linkedinLinks).forEach((link) => {
    link.href = contact.linkedin;
  });
  document.querySelectorAll(selectors.instagramLinks).forEach((link) => {
    link.href = contact.instagram;
  });
  document.querySelectorAll(selectors.facebookLinks).forEach((link) => {
    link.href = contact.facebook;
  });
}

function renderFallbackQr(canvasSelector, fallbackSelector, size) {
  const canvas = document.querySelector(canvasSelector);
  const fallback = document.querySelector(fallbackSelector);

  if (!fallback) return;

  if (canvas) {
    canvas.hidden = true;
  }

  fallback.src = `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&margin=12&data=${encodeURIComponent(
    contact.cardUrl
  )}`;
  fallback.hidden = false;
}

function renderQr(canvasSelector, fallbackSelector, width) {
  const canvas = document.querySelector(canvasSelector);

  if (!canvas || !window.QRCode?.toCanvas) {
    renderFallbackQr(canvasSelector, fallbackSelector, width);
    return;
  }

  window.QRCode.toCanvas(
    canvas,
    contact.cardUrl,
    {
      width,
      margin: 2,
      errorCorrectionLevel: "M",
      color: {
        dark: "#050914",
        light: "#f8fbff",
      },
    },
    (error) => {
      if (error) {
        renderFallbackQr(canvasSelector, fallbackSelector, width);
      }
    }
  );
}

function renderQrCodes() {
  renderQr(selectors.qrCanvas, selectors.qrFallback, 152);
  renderQr(selectors.modalQrCanvas, selectors.modalQrFallback, 292);
}

function openModal(modal, trigger) {
  if (!modal) return;

  lastModalTrigger = trigger;

  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }

  modal.querySelector("button, a")?.focus();
}

function closeModal(modal) {
  if (!modal) return;

  if (typeof modal.close === "function") {
    modal.close();
  } else {
    modal.removeAttribute("open");
    restoreFocus();
  }
}

function restoreFocus() {
  if (lastModalTrigger instanceof HTMLElement) {
    lastModalTrigger.focus();
  }
}

function bindModal(modalSelector, openSelector, closeSelector) {
  const modal = document.querySelector(modalSelector);

  document.querySelector(openSelector)?.addEventListener("click", (event) => {
    openModal(modal, event.currentTarget);
  });

  document.querySelector(closeSelector)?.addEventListener("click", () => {
    closeModal(modal);
  });

  modal?.addEventListener("close", restoreFocus);
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal(modal);
    }
  });

  return modal;
}

function bindEvents() {
  const qrModal = bindModal(selectors.qrModal, selectors.openQr, selectors.closeQr);
  const instagramModal = bindModal(
    selectors.instagramModal,
    selectors.openInstagram,
    selectors.closeInstagram
  );

  document.querySelector(selectors.saveContact)?.addEventListener("click", downloadVCard);
  document
    .querySelector(selectors.copyLink)
    ?.addEventListener("click", () => copyText(contact.cardUrl, "Link copied"));
  document
    .querySelector(selectors.modalCopyLink)
    ?.addEventListener("click", () => copyText(contact.cardUrl, "Link copied"));
  document
    .querySelector(selectors.copyInstagram)
    ?.addEventListener("click", () => copyText(contact.instagram, "Instagram copied"));

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;

    if (qrModal?.open) {
      closeModal(qrModal);
    }

    if (instagramModal?.open) {
      closeModal(instagramModal);
    }
  });
}

setCardUrls();
setContactLinks();
bindEvents();
window.addEventListener("load", renderQrCodes);
