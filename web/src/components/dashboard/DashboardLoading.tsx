export default function DashboardLoading() {
  return (
    <section className="grid dashboardLoadingGrid" aria-label="Loading dashboard">
      <div className="card loadingCard">
        <div className="skeleton title"></div>
        <div className="skeleton hero"></div>
      </div>
      <div className="card loadingCard">
        <div className="skeleton title"></div>
        <div className="skeleton block"></div>
      </div>
      <div className="card loadingCard">
        <div className="skeleton title"></div>
        <div className="skeleton block"></div>
      </div>
    </section>
  );
}
