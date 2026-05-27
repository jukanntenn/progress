"use client";

import { useLocale as useNextIntlLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

const LOCALES = ["en", "zh-Hans"] as const;
export type SupportedLocale = (typeof LOCALES)[number];

export function useLocale() {
  const locale = useNextIntlLocale() as SupportedLocale;
  const router = useRouter();

  const setLocale = useCallback(
    (newLocale: SupportedLocale) => {
      document.cookie = `NEXT_LOCALE=${newLocale};path=/;max-age=31536000;SameSite=Lax`;
      router.refresh();
    },
    [router],
  );

  return { locale, setLocale, locales: LOCALES };
}
