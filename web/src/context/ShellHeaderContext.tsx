/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type Dispatch, type ReactNode, type SetStateAction } from "react";

type ShellHeaderContextValue = {
  hasProvider: boolean;
  setHeaderActions: Dispatch<SetStateAction<ReactNode>>;
};

const noopSetHeaderActions: Dispatch<SetStateAction<ReactNode>> = () => undefined;

const ShellHeaderContext = createContext<ShellHeaderContextValue>({
  hasProvider: false,
  setHeaderActions: noopSetHeaderActions,
});

export function ShellHeaderProvider({
  children,
  setHeaderActions,
}: {
  children: ReactNode;
  setHeaderActions: Dispatch<SetStateAction<ReactNode>>;
}) {
  return (
    <ShellHeaderContext.Provider value={{ hasProvider: true, setHeaderActions }}>
      {children}
    </ShellHeaderContext.Provider>
  );
}

export function useShellHeader() {
  return useContext(ShellHeaderContext);
}
