import { Navigate, useLocation } from "react-router-dom";

/** A moved page's old path (#450): redirect to its new one, keeping the query string and hash
 * (an Inbox link's `?card=`), which a plain `<Navigate to>` drops. */
export default function RedirectKeepingSearch({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: to, search, hash }} replace />;
}
