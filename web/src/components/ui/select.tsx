import { cn } from "@/lib/utils";

type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export function Select({ className, children, ...props }: SelectProps) {
  return (
    <select
      className={cn(
        "glass-input flex h-10 w-full rounded-md px-3 py-2 text-sm",
        "ring-offset-background",
        "transition-all duration-200 ease-out",
        "hover:border-ring/40",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "cursor-pointer appearance-none bg-no-repeat bg-right",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
