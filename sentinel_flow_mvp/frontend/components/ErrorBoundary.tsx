import React, { Component, ErrorInfo, ReactNode } from "react";
import { AlertCircle } from "lucide-react";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-8 border border-red-500/20 bg-red-500/10 rounded-xl">
          <AlertCircle className="w-8 h-8 text-red-400 mb-3" />
          <h2 className="text-red-400 font-semibold">Visualization Error - Data Malformed</h2>
          <p className="text-red-300/70 text-sm mt-2 max-w-sm text-center">
            The data passed to the visualization component was malformed or unexpected.
          </p>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
