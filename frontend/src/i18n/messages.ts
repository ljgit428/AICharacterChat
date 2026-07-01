import { enUSMessages } from "./en-US";
import { zhCNMessages } from "./zh-CN";

export type SupportedLocale = "zh-CN" | "en-US";

export const DEFAULT_LOCALE: SupportedLocale = "zh-CN";

type DeepI18nShape<T> =
  T extends string ? string :
  T extends number ? number :
  T extends boolean ? boolean :
  T extends (...args: infer Args) => infer ReturnValue ? (...args: Args) => ReturnValue :
  T extends readonly (infer Item)[] ? ReadonlyArray<DeepI18nShape<Item>> :
  T extends object ? { [Key in keyof T]: DeepI18nShape<T[Key]> } :
  T;

export const SUPPORTED_UI_LOCALES: ReadonlyArray<{
  value: SupportedLocale;
  englishLabel: string;
  nativeLabel: string;
}> = [
  { value: "zh-CN", englishLabel: "Simplified Chinese", nativeLabel: "简体中文" },
  { value: "en-US", englishLabel: "English", nativeLabel: "English" },
] as const;

export function normalizeLocale(value?: string | null): SupportedLocale {
  const normalized = (value || "").trim().toLowerCase();

  if (normalized === "en" || normalized === "en-us" || normalized === "english") {
    return "en-US";
  }

  return "zh-CN";
}

export type I18nMessages = DeepI18nShape<typeof zhCNMessages>;

export const messages: Record<SupportedLocale, I18nMessages> = {
  "zh-CN": zhCNMessages,
  "en-US": enUSMessages,
};
