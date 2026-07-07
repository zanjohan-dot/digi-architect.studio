"use strict";

/**
 * Clean v4 digital name card script
 * Handles:
 * - Contact link configuration
 * - QR rendering with local image fallback
 * - Save Contact vCard download
 * - Copy link actions
 * - QR and Instagram modals
 */

const CONTACT = {
  name: "Zan Johan",
  givenName: "Zan",
  familyName: "Johan",
  title: "Digital Systems Architect",
  company: "The Digital Systems Architect",

  phoneDisplay: "+65 8987 8714",
  whatsappNumber: "6589878714",
  email: "zanj@digi-architect.studio",

  website: "https://digi-architect.studio",
  cardUrl: "https://digi-architect.studio/zan/",

  linkedinCompany: "https://www.linkedin.com/company/the-digital-systems-architect",
  linkedinPersonal: "https://www.linkedin.com/in/zanjohan",
  instagram: "https://www.instagram.com/digital.systems.architect",
  facebook: "https://www.facebook.com/share/17tceLy88Z/?mibextid=wwXIfr",

  qrFallbackImage: "assets/card-qr.png",
};

const SELECTOR = {
  cardUrlLinks: "[data-card-url], [data-modal-card-url]",

  websiteLinks: "[data-website-link]",
  whatsappLinks: "[data-whatsapp-link]",
  emailLinks: "[data-email-link]",
  linkedinCompanyLinks: "[data-linkedin-link]",
  linkedinPersonalLinks: "[data-personal-linkedin-link]",
  instagramLinks: "[data-instagram-link]",
  facebookLinks: "[data-facebook-link]",

  qrCanvas: "[data-qr-canvas]",
  qrFallback: "[data-qr-fallback]",
  modalQrCanvas: "[data-modal-qr-canvas]",
  modalQrFallback: "[data-modal-qr-fallback]",

  qrModal: "[data-qr-modal]",
  openQrModal: "[data-open-qr]",
  closeQrModal: "[data-close-qr]",

  instagramModal: "[data-instagram-modal]",
  openInstagramModal: "[data-open-instagram]",
  closeInstagramModal: "[data-close-instagram]",

  saveContact: "[data-save-contact]",
  copyLink: "[data-copy-link]",
  modalCopyLink: "[data-modal-copy-link]",
  copyInstagram: "[data-copy-instagram]",

  toast: "[data-toast]",
};

let lastModalTrigger = null;
let toastTimer = null;

/* ---------- Utility helpers ---------- */

function displayUrl(url) {
  return String(url).replace(/^https?:\/\//, "").replace(/\/$/, "");
}

function getElement(selector) {
  return document.querySelector(selector);
}

function getElements(selector) {
  return Array.from(document.querySelectorAll(selector));
}

function setLink(selector, href) {
  getElements(selector).forEach((element) => {
    element.href = href;
  });
}

function showToast(message) {
  const toast = getElement(SELECTOR.toast);

  if (!toast) return;

  window.clearTimeout(toastTimer);

  toast.textContent = message;
  toast.hidden = false;

  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 1800);
}

async function copyText(text, successMessage = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const fallbackInput = document.createElement("input");

    fallbackInput.value = text;
    fallbackInput.setAttribute("readonly", "");
    fallbackInput.style.position = "fixed";
    fallbackInput.style.left = "-9999px";

    document.body.append(fallbackInput);
    fallbackInput.select();
    document.execCommand("copy");
    fallbackInput.remove();
  }

  showToast(successMessage);
}

/* ---------- Contact links ---------- */

function applyContactLinks() {
  setLink(SELECTOR.websiteLinks, CONTACT.website);
  setLink(SELECTOR.whatsappLinks, `https://wa.me/${CONTACT.whatsappNumber}`);
  setLink(SELECTOR.emailLinks, `mailto:${CONTACT.email}`);
  setLink(SELECTOR.linkedinCompanyLinks, CONTACT.linkedinCompany);
  setLink(SELECTOR.linkedinPersonalLinks, CONTACT.linkedinPersonal);
  setLink(SELECTOR.instagramLinks, CONTACT.instagram);
  setLink(SELECTOR.facebookLinks, CONTACT.facebook);

  getElements(SELECTOR.cardUrlLinks).forEach((link) => {
    link.href = CONTACT.cardUrl;
    link.textContent = displayUrl(CONTACT.cardUrl);
  });
}

/* ---------- vCard ---------- */

function escapeVCard(value) {
  return String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/\r?\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function buildVCard() {
  const lines = [
    "BEGIN:VCARD",
    "VERSION:3.0",
    `N:${escapeVCard(CONTACT.familyName)};${escapeVCard(CONTACT.givenName)};;;`,
    `FN:${escapeVCard(CONTACT.name)}`,
    `ORG:${escapeVCard(CONTACT.company)}`,
    `TITLE:${escapeVCard(CONTACT.title)}`,
    `TEL;TYPE=CELL:${escapeVCard(CONTACT.phoneDisplay)}`,
    `EMAIL;TYPE=INTERNET:${escapeVCard(CONTACT.email)}`,
    `URL:${escapeVCard(CONTACT.website)}`,
    `X-SOCIALPROFILE;TYPE=linkedin-company:${escapeVCard(CONTACT.linkedinCompany)}`,
    `X-SOCIALPROFILE;TYPE=linkedin-personal:${escapeVCard(CONTACT.linkedinPersonal)}`,
    `X-SOCIALPROFILE;TYPE=instagram:${escapeVCard(CONTACT.instagram)}`,
    `X-SOCIALPROFILE;TYPE=facebook:${escapeVCard(CONTACT.facebook)}`,
    `NOTE:${escapeVCard(`Digital card: ${CONTACT.cardUrl}`)}`,
    "END:VCARD",
  ];

  return lines.join("\r\n");
}

function downloadVCard() {
  const blob = new Blob([buildVCard()], {
    type: "text/vcard;charset=utf-8",
  });

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = "Zan-Johan.vcf";

  document.body.append(link);
  link.click();
  link.remove();

  URL.revokeObjectURL(url);

  showToast("Contact saved");
}

/* ---------- QR code ---------- */

function showQrFallback(canvasSelector, fallbackSelector) {
  const canvas = getElement(canvasSelector);
  const fallback = getElement(fallbackSelector);

  if (canvas) {
    canvas.hidden = true;
  }

  if (fallback) {
    fallback.src = CONTACT.qrFallbackImage;
    fallback.hidden = false;
  }
}

function renderQr(canvasSelector, fallbackSelector, size) {
  const canvas = getElement(canvasSelector);
  const fallback = getElement(fallbackSelector);

  if (!canvas || !window.QRCode?.toCanvas) {
    showQrFallback(canvasSelector, fallbackSelector);
    return;
  }

  window.QRCode.toCanvas(
    canvas,
    CONTACT.cardUrl,
    {
      width: size,
      margin: 2,
      errorCorrectionLevel: "M",
      color: {
        dark: "#050914",
        light: "#f8fbff",
      },
    },
    (error) => {
      if (error) {
        showQrFallback(canvasSelector, fallbackSelector);
        return;
      }

      canvas.hidden = false;

      if (fallback) {
        fallback.hidden = true;
      }
    }
  );
}

function renderQrCodes() {
  renderQr(SELECTOR.qrCanvas, SELECTOR.qrFallback, 152);
  renderQr(SELECTOR.modalQrCanvas, SELECTOR.modalQrFallback, 292);
}

/* ---------- Modals ---------- */

function openModal(modal, trigger) {
  if (!modal) return;

  lastModalTrigger = trigger instanceof HTMLElement ? trigger : null;

  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }

  const firstFocusable = modal.querySelector(
    "button, a, input, select, textarea, [tabindex]:not([tabindex='-1'])"
  );

  firstFocusable?.focus();
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

function bindModal({ modalSelector, openSelector, closeSelector }) {
  const modal = getElement(modalSelector);
  const openButton = getElement(openSelector);
  const closeButton = getElement(closeSelector);

  openButton?.addEventListener("click", (event) => {
    openModal(modal, event.currentTarget);
  });

  closeButton?.addEventListener("click", () => {
    closeModal(modal);
  });

  modal?.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal(modal);
    }
  });

  modal?.addEventListener("close", restoreFocus);

  return modal;
}

function bindModals() {
  const qrModal = bindModal({
    modalSelector: SELECTOR.qrModal,
    openSelector: SELECTOR.openQrModal,
    closeSelector: SELECTOR.closeQrModal,
  });

  const instagramModal = bindModal({
    modalSelector: SELECTOR.instagramModal,
    openSelector: SELECTOR.openInstagramModal,
    closeSelector: SELECTOR.closeInstagramModal,
  });

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

/* ---------- Event binding ---------- */

function bindActions() {
  getElement(SELECTOR.saveContact)?.addEventListener("click", downloadVCard);

  getElement(SELECTOR.copyLink)?.addEventListener("click", () => {
    copyText(CONTACT.cardUrl, "Link copied");
  });

  getElement(SELECTOR.modalCopyLink)?.addEventListener("click", () => {
    copyText(CONTACT.cardUrl, "Link copied");
  });

  getElement(SELECTOR.copyInstagram)?.addEventListener("click", () => {
    copyText(CONTACT.instagram, "Instagram copied");
  });
}

/* ---------- Init ---------- */

function init() {
  applyContactLinks();
  bindActions();
  bindModals();

  /**
   * Show local QR image immediately.
   * If QRCode library loads properly, it will replace the image with canvas later.
   */
  showQrFallback(SELECTOR.qrCanvas, SELECTOR.qrFallback);
  showQrFallback(SELECTOR.modalQrCanvas, SELECTOR.modalQrFallback);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

window.addEventListener("load", renderQrCodes);
