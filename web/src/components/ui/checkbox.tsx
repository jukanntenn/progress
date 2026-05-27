import { cn } from "@/lib/utils";

type CheckboxProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Checkbox({ className, ...props }: CheckboxProps) {
  return (
    <input
      type="checkbox"
      className={cn(
        "h-4 w-4 rounded-xs border border-border/60 ring-offset-background",
        "glass-input",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "accent-primary transition-all duration-200 ease-out",
        "cursor-pointer",
        className,
      )}
      {...props}
    />
  );
}
