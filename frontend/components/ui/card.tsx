import { cn } from "@/lib/utils";

/**
 * Shared surface primitives for a consistent look across the portal.
 *
 * `Card` is the standard elevated container (replaces the ad-hoc
 * `rounded-lg border border-slate-800 bg-slate-900/60` repeated everywhere).
 * `SectionHeading` is the small uppercase group label used inside panels.
 */

export function Card({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-slate-800 bg-slate-900/60 shadow-sm shadow-black/20",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  action,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3 border-b border-slate-800 px-5 py-4", className)}>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
        {description ? <p className="mt-0.5 text-xs text-slate-400">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function CardBody({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cn("p-5", className)}>{children}</div>;
}

export function SectionHeading({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={cn("text-[11px] font-semibold uppercase tracking-wider text-slate-500", className)}>
      {children}
    </p>
  );
}