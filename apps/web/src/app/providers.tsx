import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type PropsWithChildren, useEffect, useState } from "react";

import { useStudioStore } from "@/store/studio-store";

function StudioRuntime() {
  const resumePendingJobs = useStudioStore((state) => state.resumePendingJobs);

  useEffect(() => {
    resumePendingJobs();
  }, [resumePendingJobs]);

  return null;
}

export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 15_000,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <StudioRuntime />
      {children}
    </QueryClientProvider>
  );
}
