/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type Dispatch, type ReactNode, type SetStateAction } from "react";

type ShellHeaderContextValue = {
  hasProvider: boolean;
  /** True on a phone-width shell (#239): the page renders its own header actions under
   *  its title instead of the shell's top bar, which has no room for them. */
  actionsInPage: boolean;
  setHeaderActions: Dispatch<SetStateAction<ReactNode>>;
};

const noopSetHeaderActions: Dispatch<SetStateAction<ReactNode>> = () => undefined;

const ShellHeaderContext = createContext<ShellHeaderContextValue>({
  hasProvider: false,
  actionsInPage: false,
  setHeaderActions: noopSetHeaderActions,
});

export function ShellHeaderProvider({
  children,
  setHeaderActions,
  actionsInPage = false,
}: {
  children: ReactNode;
  setHeaderActions: Dispatch<SetStateAction<ReactNode>>;
  actionsInPage?: boolean;
}) {
  return (
    <ShellHeaderContext.Provider value={{ hasProvider: true, actionsInPage, setHeaderActions }}>
      {children}
    </ShellHeaderContext.Provider>
  );
}

export function useShellHeader() {
  return useContext(ShellHeaderContext);
}
