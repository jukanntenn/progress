import { getRequestConfig } from "next-intl/server";
import { cookies } from "next/headers";

const LOCALES = ["en", "zh-Hans"] as const;
type Locale = (typeof LOCALES)[number];

function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get("NEXT_LOCALE")?.value ?? "en";
  const locale = isLocale(cookieLocale) ? cookieLocale : "en";

  return {
    locale,
    messages: (await import(`./locales/${locale}.json`)).default,
  };
});
