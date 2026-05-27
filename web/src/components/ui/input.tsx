import { cn } from "@/lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export function Input({ className, type, error, ...props }: InputProps) {
  return (
    <input
      type={type}
      className={cn(
        "glass-input flex h-10 w-full rounded-md px-3 py-2 text-sm",
        "ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium",
        "placeholder:text-muted-foreground",
        "transition-all duration-200 ease-out",
        "hover:border-ring/40",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:border-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50",
        error && "border-error/50 focus-visible:ring-error/50 focus-visible:border-error/50",
        className,
      )}
      {...props}
    />
  );
}
