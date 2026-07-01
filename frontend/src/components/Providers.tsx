"use client";

import { Provider } from "react-redux";
import { store } from "@/store/store";
import { ApolloProvider } from "./ApolloProvider";
import { I18nProvider } from "@/i18n/provider";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <Provider store={store}>
      <I18nProvider>
        <ApolloProvider>{children}</ApolloProvider>
      </I18nProvider>
    </Provider>
  );
}
