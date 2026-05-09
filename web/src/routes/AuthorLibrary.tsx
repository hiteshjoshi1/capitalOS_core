import { createElement, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import PageShell from "../components/PageShell";
import "../App.css";
import { api, type RagAuthorLibrary, type RagLibraryAuthor, type RagLibraryContentBlock, type RagLibraryDocumentDetail, type RagLibraryDocumentSummary } from "../lib/api";

type RouteParams = {
  authorId?: string;
  documentId?: string;
};

function authorRoute(authorId: string): string {
  return `/author-library/${encodeURIComponent(authorId)}`;
}

function documentRoute(authorId: string, documentId: string): string {
  return `${authorRoute(authorId)}/documents/${encodeURIComponent(documentId)}`;
}

function authorInitials(name: string): string {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
  return initials || "?";
}

function AuthorPortrait({
  author,
  className = "",
}: {
  author: Pick<RagLibraryAuthor, "name" | "photo_url">;
  className?: string;
}) {
  if (author.photo_url) {
    return <img className={`authorLibraryPortrait ${className}`.trim()} src={author.photo_url} alt={`Photo of ${author.name}`} />;
  }

  return (
    <div className={`authorLibraryPortrait authorLibraryPortraitFallback ${className}`.trim()} aria-hidden="true">
      {authorInitials(author.name)}
    </div>
  );
}

function DocumentLinkCard({
  authorId,
  document,
}: {
  authorId: string;
  document: RagLibraryDocumentSummary;
}) {
  return (
    <Link className="authorLibraryDocumentRow authorLibraryDocumentLink" to={documentRoute(authorId, document.id)}>
      <span className="authorLibraryDocumentGlyph" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
          <path d="M6 3.5h5l3.5 3.5V16a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 4.5 16V5A1.5 1.5 0 0 1 6 3.5Z" />
          <path d="M11 3.5V7h3.5" />
        </svg>
      </span>
      <span className="authorLibraryDocumentTitle">{document.title}</span>
    </Link>
  );
}

function renderHeadingBlock(block: RagLibraryContentBlock) {
  const level = Math.min(Math.max(block.level ?? 2, 1), 6);
  const tagName = (`h${level}` as const);
  return createElement(tagName, { className: "authorLibraryBlockHeading" }, block.text);
}

function StructuredDocumentRenderer({ blocks }: { blocks: RagLibraryContentBlock[] }) {
  return (
    <div className="authorLibraryStructuredDocument" data-testid="author-library-reader-structured">
      {blocks.map((block) => {
        const key = block.block_id;
        const headingContext = typeof block.metadata?.heading_context === "string" ? block.metadata.heading_context : null;

        if (block.type === "heading" && block.text) {
          return (
            <section key={key} id={key} className="authorLibraryBlock authorLibraryBlockSection">
              {renderHeadingBlock(block)}
            </section>
          );
        }

        if (block.type === "list" && block.items?.length) {
          return (
            <section key={key} id={key} className="authorLibraryBlock">
              {headingContext ? <div className="authorLibraryBlockContext">{headingContext}</div> : null}
              <ul className="authorLibraryBlockList">
                {block.items.map((item) => (
                  <li key={`${key}:${item}`}>{item}</li>
                ))}
              </ul>
            </section>
          );
        }

        if (block.type === "quote" && block.text) {
          return (
            <blockquote key={key} id={key} className="authorLibraryBlockQuote">
              {block.text}
            </blockquote>
          );
        }

        if (block.type === "table") {
          const rows = block.table_rows ?? [];
          const header = rows.length > 1 ? rows[0] : [];
          const bodyRows = rows.length > 1 ? rows.slice(1) : rows;
          return (
            <section key={key} id={key} className="authorLibraryBlock authorLibraryBlockTable">
              {headingContext ? <div className="authorLibraryBlockContext">{headingContext}</div> : null}
              {rows.length ? (
                <div className="authorLibraryTableScroller">
                  <table className="authorLibraryTable" data-testid="author-library-table">
                    {header.length ? (
                      <thead>
                        <tr>
                          {header.map((cell, index) => (
                            <th key={`${key}:header:${index}`} scope="col">{cell}</th>
                          ))}
                        </tr>
                      </thead>
                    ) : null}
                    <tbody>
                      {bodyRows.map((row, rowIndex) => (
                        <tr key={`${key}:row:${rowIndex}`}>
                          {row.map((cell, cellIndex) => (
                            <td key={`${key}:cell:${rowIndex}:${cellIndex}`}>{cell}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <pre className="authorLibraryTableFallback">{block.table_markdown ?? block.text ?? ""}</pre>
              )}
            </section>
          );
        }

        if (block.text) {
          return (
            <p key={key} id={key} className="authorLibraryBlockParagraph">
              {block.text}
            </p>
          );
        }

        return null;
      })}
    </div>
  );
}

export default function AuthorLibrary() {
  const { authorId = "", documentId = "" } = useParams<RouteParams>();
  const isGallery = !authorId;
  const isReader = Boolean(authorId && documentId);
  const readerSurfaceRef = useRef<HTMLDivElement | null>(null);

  const [authors, setAuthors] = useState<RagLibraryAuthor[]>([]);
  const [authorsLoading, setAuthorsLoading] = useState(false);
  const [library, setLibrary] = useState<RagAuthorLibrary | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [documentDetail, setDocumentDetail] = useState<RagLibraryDocumentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isGallery) return;
    let cancelled = false;
    const loadAuthors = async () => {
      setAuthorsLoading(true);
      try {
        const data = await api.ragLibraryAuthors();
        if (cancelled) return;
        setAuthors(data);
        setError(null);
      } catch (err: unknown) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setAuthorsLoading(false);
      }
    };
    void loadAuthors();
    return () => {
      cancelled = true;
    };
  }, [isGallery]);

  useEffect(() => {
    if (!authorId) return;
    let cancelled = false;
    const loadLibrary = async () => {
      setLibraryLoading(true);
      try {
        const data = await api.ragAuthorLibrary(authorId);
        if (cancelled) return;
        setLibrary(data);
        setError(null);
      } catch (err: unknown) {
        if (cancelled) return;
        setLibrary(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLibraryLoading(false);
      }
    };
    void loadLibrary();
    return () => {
      cancelled = true;
    };
  }, [authorId]);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    const loadDocument = async () => {
      setDetailLoading(true);
      try {
        const data = await api.ragLibraryDocument(documentId);
        if (cancelled) return;
        setDocumentDetail(data);
        setError(null);
      } catch (err: unknown) {
        if (cancelled) return;
        setDocumentDetail(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    };
    void loadDocument();
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === readerSurfaceRef.current);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, []);

  const toggleFullscreen = async () => {
    if (!readerSurfaceRef.current) return;

    if (document.fullscreenElement === readerSurfaceRef.current) {
      if (document.exitFullscreen) {
        await document.exitFullscreen();
      }
      setIsFullscreen(false);
      return;
    }

    if (readerSurfaceRef.current.requestFullscreen) {
      await readerSurfaceRef.current.requestFullscreen();
      setIsFullscreen(true);
      return;
    }

    setIsFullscreen((current) => !current);
  };

  const groupedSections = useMemo(() => library?.groups ?? [], [library]);
  const title = isGallery
    ? "Author Library"
    : isReader
      ? (documentDetail?.title ?? "Reader")
      : (library?.author.name ?? "Author Library");

  return (
    <PageShell
      title={title}
      headerActions={(
        <div className="authorLibraryHeaderActions">
          {!isGallery ? <Link className="btn" to="/author-library">All authors</Link> : null}
          {authorId && isReader ? (
            <>
              <Link className="btn" to={authorRoute(authorId)}>Back to library</Link>
              <button className="btn" type="button" onClick={() => void toggleFullscreen()}>
                {isFullscreen ? "Exit fullscreen" : "Fullscreen"}
              </button>
            </>
          ) : null}
        </div>
      )}
    >
      <div className="dashboardWrap">
        {error ? (
          <div className="card error">
            <div className="cardTitle">Unable to load author library</div>
            <pre className="pre">{error}</pre>
          </div>
        ) : null}

        {isGallery ? (
          <>
            {authorsLoading ? (
              <div className="card">
                <div className="cardTitle">Loading authors</div>
                <div className="muted">Fetching available corpora and gallery metadata...</div>
              </div>
            ) : null}

            {!authorsLoading && !authors.length && !error ? (
              <div className="card">
                <div className="cardTitle">No author corpus available yet</div>
                <div className="muted">
                  Ingested logical documents will appear here once an author corpus has been loaded into CapitalOS.
                </div>
              </div>
            ) : null}

            {authors.length ? (
              <section className="grid authorLibraryGallery" aria-label="Author gallery">
                {authors.map((author) => (
                  <Link
                    key={author.id}
                    className="card authorLibraryGalleryCard authorLibraryGalleryCardLink"
                    aria-label={author.name}
                    to={authorRoute(author.id)}
                  >
                    <div className="authorLibraryGalleryHeader">
                      <AuthorPortrait author={author} className="authorLibraryGalleryPortrait" />
                      <div className="authorLibraryGalleryIdentity">
                        <h2>{author.name}</h2>
                      </div>
                    </div>
                  </Link>
                ))}
              </section>
            ) : null}
          </>
        ) : null}

        {authorId && !isReader ? (
          <>
            {libraryLoading ? (
              <div className="card">
                <div className="cardTitle">Loading library</div>
                <div className="muted">Fetching grouped logical documents for this author...</div>
              </div>
            ) : null}

            {library ? (
              <>
                <section className="grid authorLibraryOverview">
                  <div className="card authorLibraryAuthorCard authorLibraryAuthorCardMinimal">
                    <div className="authorLibraryGalleryHeader">
                      <AuthorPortrait author={library.author} />
                      <div className="authorLibraryGalleryIdentity">
                        <h2>{library.author.name}</h2>
                      </div>
                    </div>
                  </div>
                </section>

                <section className="grid authorLibraryLibraryPage">
                  <div className="card authorLibraryListPanel">
                    <div className="cardTitle">Writings</div>
                    {groupedSections.length ? (
                      <div className="authorLibraryGroupStack">
                        {groupedSections.map((group) => (
                          <section key={`${group.field}:${group.value}`} className="authorLibraryGroup">
                            <div className="authorLibraryGroupHeader">
                              <h3>{group.label}</h3>
                            </div>
                            {group.secondary_groups.length ? (
                              <div className="authorLibrarySecondaryStack">
                                {group.secondary_groups.map((secondaryGroup) => (
                                  <div key={`${group.value}:${secondaryGroup.value}`} className="authorLibrarySecondaryGroup">
                                    <div className="cardTitle">{secondaryGroup.label}</div>
                                    <div className="authorLibraryDocumentStack">
                                      {secondaryGroup.documents.map((document) => (
                                        <DocumentLinkCard key={document.id} authorId={authorId} document={document} />
                                      ))}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="authorLibraryDocumentStack">
                                {group.documents.map((document) => (
                                  <DocumentLinkCard key={document.id} authorId={authorId} document={document} />
                                ))}
                              </div>
                            )}
                          </section>
                        ))}
                      </div>
                    ) : (
                      <div className="authorLibraryDocumentStack">
                        {library.documents.map((document) => (
                          <DocumentLinkCard key={document.id} authorId={authorId} document={document} />
                        ))}
                      </div>
                    )}
                  </div>
                </section>
              </>
            ) : null}
          </>
        ) : null}

        {authorId && isReader ? (
          <section className="grid authorLibraryReaderPage">
            {(libraryLoading || detailLoading) ? (
              <div className="card">
                <div className="cardTitle">Loading reader</div>
                <div className="muted">Fetching the logical document and its related metadata...</div>
              </div>
            ) : null}

            {documentDetail ? (
              <div
                ref={readerSurfaceRef}
                className={`card authorLibraryReaderSurface${isFullscreen ? " authorLibraryReaderSurfaceFullscreen" : ""}`}
                data-testid="author-library-reader-surface"
              >
                <div className="authorLibraryReaderContent">
                  <div className="authorLibraryReaderHeader">
                    <div>
                      <div className="authorLibraryBreadcrumbs">
                        <Link to="/author-library">Authors</Link>
                        <span aria-hidden="true">/</span>
                        <Link to={authorRoute(authorId)}>{library?.author.name ?? "Library"}</Link>
                        <span aria-hidden="true">/</span>
                        <span>{documentDetail.title}</span>
                      </div>
                      <h2>{documentDetail.title}</h2>
                      <div className="authorLibraryReaderMeta">
                        <span>{documentDetail.author_name ?? documentDetail.author_id ?? "Unknown author"}</span>
                        {documentDetail.publication_label ? <span>{documentDetail.publication_label}</span> : null}
                      </div>
                    </div>
                  </div>

                  {documentDetail.source_url ? (
                    <a className="authorLibrarySourceLink" href={documentDetail.source_url} rel="noreferrer" target="_blank">
                      Open source
                    </a>
                  ) : null}

                  {documentDetail.content_blocks?.length ? (
                    <StructuredDocumentRenderer blocks={documentDetail.content_blocks} />
                  ) : (
                    <div className="authorLibraryReaderText" data-testid="author-library-reader-text">
                      {documentDetail.clean_text}
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </PageShell>
  );
}
