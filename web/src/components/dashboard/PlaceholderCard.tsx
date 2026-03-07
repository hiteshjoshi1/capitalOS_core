type PlaceholderCardProps = {
  title: string;
  description: string;
  footer?: string;
};

export default function PlaceholderCard({ title, description, footer }: PlaceholderCardProps) {
  return (
    <div className="card placeholderCard">
      <h2>{title}</h2>
      <div className="placeholderBody">
        <div className="placeholderLine"></div>
        <div className="placeholderLine short"></div>
      </div>
      <div className="muted">{description}</div>
      {footer ? <div className="hint">{footer}</div> : null}
      <div className="hintTag">Placeholder</div>
    </div>
  );
}
