import Link from "next/link";

export default function ExecutionExplorerPage() {
  return (
    <div className="py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-headline font-bold text-primary">
            Execution Explorer
          </h1>
          <p className="text-on-surface-variant text-sm">
            Trace & cost visibility
          </p>
        </div>
      </div>

      <div className="bg-surface-container rounded-2xl p-6 text-on-surface-variant text-sm">
        <p>Coming soon — execution traces, token costs, and latency breakdowns.</p>
        <p className="mt-3">
          <Link href="/logs/legacy" className="underline text-primary">
            Legacy logs →
          </Link>
        </p>
      </div>
    </div>
  );
}
