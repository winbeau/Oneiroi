import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type PropsWithChildren, useState } from "react";

import { demoMode } from "@/lib/api-client";

export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 10_000,
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      {demoMode && (
        <div className="fixed right-3 top-3 z-[100] rounded-full bg-[var(--color-warning)] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-white shadow-lg">
          Demo mode
        </div>
      )}
      {children}
    </QueryClientProvider>
  );
}
