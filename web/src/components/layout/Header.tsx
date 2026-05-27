"use client";

import { cn } from "@/lib/utils";
import { useLocale, type SupportedLocale } from "@/hooks/use-locale";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { Settings, Rss, Contrast, Moon, Sun, Globe, ChevronDown } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const LANGUAGE_LABELS: Record<SupportedLocale, string> = {
  en: "English",
  "zh-Hans": "简体中文",
};

function LanguageSelector() {
  const t = useTranslations();
  const { locale, setLocale, locales } = useLocale();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!dropdownRef.current) return;
      if (dropdownRef.current.contains(event.target as Node)) return;
      setIsOpen(false);
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1.5",
          "h-9 px-2 rounded-md",
          "text-sm font-medium",
          "text-muted-foreground hover:text-foreground hover:bg-accent/50",
          "transition-all duration-200 ease-out active:scale-95",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        )}
        aria-label={t("nav.language")}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
      >
        <Globe className="h-4 w-4" />
        <span className="hidden sm:inline">{LANGUAGE_LABELS[locale]}</span>
        <ChevronDown
          className={cn(
            "hidden sm:block h-3 w-3 transition-transform duration-200",
            isOpen && "rotate-180",
          )}
        />
      </button>

      {isOpen && (
        <div
          className={cn(
            "absolute right-0 top-full mt-1",
            "min-w-[140px]",
            "glass-card p-1",
            "animate-slide-down",
            "z-50",
          )}
          role="listbox"
          aria-label={t("nav.language")}
        >
          {locales.map((lang) => (
            <button
              key={lang}
              type="button"
              onClick={() => {
                setLocale(lang);
                setIsOpen(false);
              }}
              className={cn(
                "w-full flex items-center",
                "px-3 py-2 rounded-md",
                "text-sm text-left",
                "transition-colors duration-150",
                "hover:bg-accent/50",
                locale === lang
                  ? "text-foreground bg-accent/30"
                  : "text-muted-foreground hover:text-foreground",
              )}
              role="option"
              aria-selected={locale === lang}
            >
              {LANGUAGE_LABELS[lang]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Header() {
  const t = useTranslations();
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const isConfigActive = pathname === "/config";

  const cycleTheme = () => {
    if (theme === "system") setTheme("light");
    else if (theme === "light") setTheme("dark");
    else setTheme("system");
  };

  const preference = mounted ? theme ?? "system" : "system";

  return (
    <>
      <a
        href="#main-content"
        className={cn(
          "sr-only focus:not-sr-only",
          "focus:fixed focus:top-4 focus:left-4 focus:z-[9999]",
          "focus:px-4 focus:py-2",
          "focus:bg-primary focus:text-primary-foreground",
          "focus:rounded-md focus:shadow-lg",
          "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        )}
      >
        Skip to content
      </a>

      <header
        className={cn("glass-navbar sticky top-0 z-sticky", "transition-all duration-200 ease-out")}
      >
        <nav className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-14 items-center justify-between">
            <Link
              href="/"
              className={cn(
                "text-xl font-bold",
                "text-primary",
                "transition-colors duration-200 ease-out",
                "hover:text-primary/80",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              )}
            >
              Progress
            </Link>

            <div className="flex items-center gap-1">
              <Link
                href="/config"
                className={cn(
                  "inline-flex items-center gap-2 px-3 py-2",
                  "text-sm font-medium",
                  "rounded-md",
                  "transition-all duration-200 ease-out",
                  isConfigActive
                    ? "text-foreground bg-glass-bg-primary/60 shadow-sm"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                )}
                aria-label={t("nav.settings")}
              >
                <Settings className="h-4 w-4" />
                <span className="hidden sm:inline">{t("nav.settings")}</span>
              </Link>

              <a
                href="/api/v1/rss"
                className={cn(
                  "inline-flex items-center gap-2 px-3 py-2",
                  "text-sm font-medium",
                  "rounded-md",
                  "transition-all duration-200 ease-out",
                  "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                )}
                aria-label={t("nav.rss")}
              >
                <Rss className="h-4 w-4" />
                <span className="hidden sm:inline">{t("nav.rss")}</span>
              </a>

              <LanguageSelector />

              <button
                type="button"
                onClick={cycleTheme}
                className={cn(
                  "inline-flex items-center justify-center",
                  "h-9 w-9 rounded-md",
                  "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                  "transition-all duration-200 ease-out active:scale-95",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                )}
                aria-label={preference === "system" ? t("nav.theme.system") : preference === "dark" ? t("nav.theme.dark") : t("nav.theme.light")}
              >
                {preference === "system" ? (
                  <Contrast className="h-4 w-4" />
                ) : preference === "dark" ? (
                  <Moon className="h-4 w-4" />
                ) : (
                  <Sun className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
        </nav>
      </header>
    </>
  );
}
