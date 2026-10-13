// Tests render inside the i18n provider. Existing tests use English (lang="en"); the Persian default has its own
// tests (i18n.test.tsx, plate_search.test.tsx).
import { RenderOptions, render as rtl } from "@testing-library/react";
import { ReactElement, ReactNode } from "react";
import { I18nProvider, Lang } from "../i18n";

export function render(ui: ReactElement, opts: RenderOptions & { lang?: Lang } = {}) {
  const { lang = "en", ...rest } = opts;
  return rtl(ui, { wrapper: ({ children }: { children: ReactNode }) => <I18nProvider lang={lang}>{children}</I18nProvider>, ...rest });
}
