import { cn } from "@/lib/utils";

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export function Textarea({ className, error, ...props }: TextareaProps) {
  return (
    <textarea
      className={cn(
        "glass-input flex min-h-[80px] w-full rounded-md px-3 py-2",
        "text-sm ring-offset-background placeholder:text-muted-foreground",
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
