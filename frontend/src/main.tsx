import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "./api";
import "@fontsource-variable/schibsted-grotesk";
import "./styles.css";
import { App } from "./App";
import { AppProvider } from "./state";

const client = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1, staleTime: 5000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <AppProvider>
        <App />
      </AppProvider>
    </QueryClientProvider>
  </StrictMode>,
);
