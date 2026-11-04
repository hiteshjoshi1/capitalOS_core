import { Component, type ErrorInfo, type ReactNode } from "react";

import LoadError from "./LoadError";

type Props = {
  /** Changing this (the route path) clears a caught error, so navigating away recovers. */
  resetKey: string;
  children: ReactNode;
};

type State = { error: Error | null; resetKey: string };

/**
 * Route-level error boundary (#151, review #130 finding 7.5): one page throwing while it
 * renders shows a "this page failed" card inside the shell, instead of blanking the whole
 * app. The sidebar and header stay usable; "Try again" re-renders the page, and moving to
 * another route clears the error.
 */
export default class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey !== state.resetKey) {
      return { error: null, resetKey: props.resetKey };
    }
    return null;
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept in the console for debugging; nothing is sent anywhere.
    console.error("Route render failed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <LoadError
          title="This page failed to load"
          error="Something went wrong while showing this page. The rest of the app still works."
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
