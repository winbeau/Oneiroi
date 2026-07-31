import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "@/components/layout/app-shell";
import { AssetsPage } from "@/features/assets/assets-page";
import { CreatePage } from "@/features/create/create-page";
import { InspirationPage } from "@/features/inspiration/inspiration-page";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate replace to="/create" /> },
      { path: "/inspiration", element: <InspirationPage /> },
      { path: "/create", element: <CreatePage /> },
      { path: "/assets", element: <AssetsPage /> },
    ],
  },
]);
