import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";

export default function AppShell() {
  return (
    <div className="appShell">
      <Sidebar />
      <main className="appShellMain">
        <Outlet />
      </main>
    </div>
  );
}
