"use client";

import { Toast } from "@base-ui/react/toast";
import { cn } from "@/lib/utils";
import { X, CheckCircle, AlertCircle, Info, AlertTriangle } from "lucide-react";
import { type ReactNode } from "react";

export const toastManager = Toast.createToastManager();

const toastIcons: Record<string, ReactNode> = {
  success: <CheckCircle className="h-4 w-4" />,
  error: <AlertCircle className="h-4 w-4" />,
  info: <Info className="h-4 w-4" />,
  warning: <AlertTriangle className="h-4 w-4" />,
};

const toastColors: Record<string, string> = {
  success: "bg-success text-success-foreground",
  error: "bg-error text-error-foreground",
  info: "bg-info text-info-foreground",
  warning: "bg-warning text-warning-foreground",
};

function ToastList() {
  const { toasts } = Toast.useToastManager();

  return toasts.map((t) => (
    <Toast.Root
      key={t.id}
      toast={t}
      className={cn(
        "flex items-center gap-3 rounded-md px-4 py-3 text-sm",
        "shadow-glass transition-all duration-200 ease-out",
        "data-[starting-style]:opacity-0 data-[starting-style]:translate-x-2",
        "data-[ending-style]:opacity-0 data-[ending-style]:translate-x-2",
        toastColors[t.type ?? "info"] ?? "bg-info text-info-foreground",
      )}
    >
      {toastIcons[t.type ?? "info"]}
      <Toast.Content className="flex-1">
        <Toast.Title className="font-medium" />
        <Toast.Description className="mt-0.5 text-sm opacity-80" />
      </Toast.Content>
      <Toast.Close
        className={cn(
          "ml-2 rounded p-1 opacity-70 hover:opacity-100",
          "transition-opacity duration-150",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50",
        )}
        aria-label="Dismiss notification"
      >
        <X className="h-3 w-3" />
      </Toast.Close>
    </Toast.Root>
  ));
}

export function ToastProvider({ children }: { children: ReactNode }) {
  return (
    <Toast.Provider toastManager={toastManager} timeout={4000}>
      {children}
      <Toast.Portal>
        <Toast.Viewport className="fixed bottom-4 right-4 z-[1080] flex w-full max-w-sm flex-col gap-2 pointer-events-none">
          <ToastList />
        </Toast.Viewport>
      </Toast.Portal>
    </Toast.Provider>
  );
}

type ToastType = "success" | "error" | "info" | "warning";

function createToastMethod(type: ToastType) {
  return (message: string, _type?: ToastType) => {
    toastManager.add({ title: message, type });
  };
}

export const showToast = createToastMethod("info");

export function toast(
  message: string,
  type: ToastType = "info",
) {
  toastManager.add({ title: message, type });
}

export const toastSuccess = createToastMethod("success");
export const toastError = createToastMethod("error");
export const toastInfo = createToastMethod("info");
export const toastWarning = createToastMethod("warning");
