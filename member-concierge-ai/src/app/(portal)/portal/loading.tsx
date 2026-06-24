import { Skeleton } from "@/components/ui/Skeleton";

export default function PortalLoading() {
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-40 w-full" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-36 w-full" />
        <Skeleton className="h-36 w-full" />
        <Skeleton className="h-36 w-full" />
      </div>
    </div>
  );
}
