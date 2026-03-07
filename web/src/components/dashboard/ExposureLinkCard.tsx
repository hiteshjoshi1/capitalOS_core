import { Link } from "react-router-dom";

type ExposureLinkCardProps = {
  title: string;
  value: string;
  subtitle: string;
  to: string;
};

export default function ExposureLinkCard({ title, value, subtitle, to }: ExposureLinkCardProps) {
  return (
    <Link to={to} className="card exposureLinkCard" aria-label={`${title} details`}>
      <h2>{title}</h2>
      <div className="big small">{value}</div>
      <div className="muted">{subtitle}</div>
      <span className="exposureCardCta">Open details</span>
    </Link>
  );
}
