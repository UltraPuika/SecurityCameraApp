import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { detectLanguage } from "./detect";
import en from "./locales/en.json";
import lv from "./locales/lv.json";

export { LANGUAGES, type Language } from "./detect";

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, lv: { translation: lv } },
  lng: detectLanguage(typeof navigator === "undefined" ? [] : navigator.languages),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
});

export default i18n;
