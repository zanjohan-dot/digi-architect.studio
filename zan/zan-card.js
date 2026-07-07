"use strict";

/**
 * Zan Johan Digital Name Card
 * Clean static QR version
 *
 * This script handles:
 * - Contact link setup
 * - Save Contact vCard
 * - Copy card link
 * - QR modal
 * - Instagram modal
 * - Toast messages
 *
 * It does NOT generate QR codes.
 * The QR code is a static image: assets/card-qr.png
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

/* ----------------------------------------
   Helpers
---------------------------------------- */

function getElement(selector) {
  return document.querySelector(selector);
}

function getElements(selector) {
  return Array.from(document.querySelectorAll(selector));
}

function displayUrl(url) {
  return String(url).replace(/^https?:\/\//, "").replace(/\/$/, "");
}

function setHref(selector, href) {
  getElements(selector).forEach((element) => {
    element.href = href;
  });
}

/* ----------------------------------------
   Apply live links
---------------------------------------- */

function applyContactLinks() {
  setHref(SELECTOR.websiteLinks, CONTACT.website);
  setHref(SELECTOR.whatsappLinks, `https://wa.me/${CONTACT.whatsappNumber}`);
  setHref(SELECTOR.emailLinks, `mailto:${CONTACT.email}`);
  setHref(SELECTOR.linkedinCompanyLinks, CONTACT.linkedinCompany);
  setHref(SELECTOR.linkedinPersonalLinks, CONTACT.linkedinPersonal);
  setHref(SELECTOR.instagramLinks, CONTACT.instagram);
  setHref(SELECTOR.facebookLinks, CONTACT.facebook);

  getElements(SELECTOR.cardUrlLinks).forEach((link) => {
    link.href = CONTACT.cardUrl;
    link.textContent = displayUrl(CONTACT.cardUrl);
  });
}

/* ----------------------------------------
   Toast
---------------------------------------- */

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

/* ----------------------------------------
   Copy text
---------------------------------------- */

async function copyText(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const input = document.createElement("input");

    input.value = text;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.left = "-9999px";

    document.body.append(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }

  showToast(successMessage);
}

/* ----------------------------------------
   vCard
---------------------------------------- */

function escapeVCard(value) {
  return String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/\r?\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function buildVCard() {
  return [
    "BEGIN:VCARD",
    "VERSION:3.0",

    `N:${escapeVCard(CONTACT.familyName)};${escapeVCard(CONTACT.givenName)};;;`,
    `FN:${escapeVCard(CONTACT.name)}`,
    `ORG:${escapeVCard(CONTACT.company)}`,
    `TITLE:${escapeVCard(CONTACT.title)}`,
    `TEL;TYPE=CELL:${escapeVCard(CONTACT.phoneDisplay)}`,
    `EMAIL;TYPE=INTERNET:${escapeVCard(CONTACT.email)}`,

    `item1.URL:${escapeVCard(CONTACT.website)}`,
    "item1.X-ABLabel:Website",

    `item2.URL:${escapeVCard(CONTACT.cardUrl)}`,
    "item2.X-ABLabel:Digital Card",

    `item3.URL:${escapeVCard(CONTACT.linkedinCompany)}`,
    "item3.X-ABLabel:LinkedIn Company",

    `item4.URL:${escapeVCard(CONTACT.linkedinPersonal)}`,
    "item4.X-ABLabel:LinkedIn Personal",

    `item5.URL:${escapeVCard(CONTACT.instagram)}`,
    "item5.X-ABLabel:Instagram",

    `item6.URL:${escapeVCard(CONTACT.facebook)}`,
    "item6.X-ABLabel:Facebook",

    `NOTE:${escapeVCard(
      [
        `Digital card: ${CONTACT.cardUrl}`,
        `Website: ${CONTACT.website}`,
        `LinkedIn Company: ${CONTACT.linkedinCompany}`,
        `LinkedIn Personal: ${CONTACT.linkedinPersonal}`,
        `Instagram: ${CONTACT.instagram}`,
        `Facebook: ${CONTACT.facebook}`,
      ].join("\n")
    )}`,

    "END:VCARD",
  ].join("\r\n");
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

/* ----------------------------------------
   Modals
---------------------------------------- */

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

function bindModal(modalSelector, openSelector, closeSelector) {
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
  const qrModal = bindModal(
    SELECTOR.qrModal,
    SELECTOR.openQrModal,
    SELECTOR.closeQrModal
  );

  const instagramModal = bindModal(
    SELECTOR.instagramModal,
    SELECTOR.openInstagramModal,
    SELECTOR.closeInstagramModal
  );

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

/* ----------------------------------------
   Button actions
---------------------------------------- */

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

/* ----------------------------------------
   Init
---------------------------------------- */

function init() {
  applyContactLinks();
  bindActions();
  bindModals();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
