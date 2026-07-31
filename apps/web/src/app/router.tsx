import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "@/components/layout/app-shell";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate replace to="/create" /> },
      {
        path: "/inspiration",
        lazy: async () => {
          const { InspirationPage } = await import(
            "@/features/inspiration/inspiration-page"
          );
          return { Component: InspirationPage };
        },
      },
      {
        path: "/create",
        lazy: async () => {
          const { CreatePage } = await import("@/features/create/create-page");
          return { Component: CreatePage };
        },
      },
      {
        path: "/assets",
        lazy: async () => {
          const { AssetsPage } = await import("@/features/assets/assets-page");
          return { Component: AssetsPage };
        },
      },
    ],
  },
]);
