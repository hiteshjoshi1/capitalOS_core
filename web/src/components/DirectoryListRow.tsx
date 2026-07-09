import type { ReactNode } from "react";

type DirectoryListRowProps = {
  title: ReactNode;
  meta?: ReactNode;
  right?: ReactNode;
};

export default function DirectoryListRow({ title, meta, right }: DirectoryListRowProps) {
  return (
    <div className="listRow">
      <div className="listRowMain">
        <div className="listRowTitle">{title}</div>
        {meta ? <div className="listRowMeta">{meta}</div> : null}
      </div>
      {right ? <div className="listRowValue">{right}</div> : null}
    </div>
  );
}
