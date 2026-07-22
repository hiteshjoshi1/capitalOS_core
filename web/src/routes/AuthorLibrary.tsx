import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import PageShell from "../components/PageShell";
import "../App.css";
import {
  api,
  type RagAuthorLibrary,
  type RagLibraryAuthor,
  type RagLibraryDocumentDetail,
  type RagLibraryDocumentSummary,
  type RagLibraryGroup,
} from "../lib/api";

type RouteParams = {
  authorId?: string;
  documentId?: string;
};

type DecadeGroup = {
  label: string;
  documents: RagLibraryDocumentSummary[];
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

function authorTagLabel(author: Pick<RagLibraryAuthor, "collections" | "work_types">): string | null {
  return author.collections[0] ?? author.work_types[0] ?? null;
}

function docCountLabel(count: number): string {
  return `${count} document${count === 1 ? "" : "s"}`;
}

/**
 * Buckets exact-year groups into decades (e.g. "2020s") to match the Author
 * Library redesign. Only meaningful when the backend grouped by publication
 * year — other primary fields (collection, work_type, ...) keep their
 * existing group/secondary-group structure.
 */
function groupDocumentsByDecade(groups: RagLibraryGroup[]): DecadeGroup[] {
  const buckets = new Map<string, { order: number; documents: RagLibraryDocumentSummary[] }>();
  for (const group of groups) {
    const year = Number(group.value);
    const hasYear = group.value != null && Number.isFinite(year);
    const label = hasYear ? `${Math.floor(year / 10) * 10}s` : "Undated";
    const order = hasYear ? Math.floor(year / 10) * 10 : -Infinity;
    const bucket = buckets.get(label) ?? { order, documents: [] };
    bucket.documents.push(...group.documents, ...group.secondary_groups.flatMap((secondary) => secondary.documents));
    buckets.set(label, bucket);
  }
  return Array.from(buckets.entries())
    .sort((a, b) => b[1].order - a[1].order)
    .map(([label, bucket]) => ({ label, documents: bucket.documents }));
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
  const content = (
    <>
      <span className="authorLibraryDocumentGlyph" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
          <path d="M6 3.5h5l3.5 3.5V16a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 4.5 16V5A1.5 1.5 0 0 1 6 3.5Z" />
          <path d="M11 3.5V7h3.5" />
        </svg>
      </span>
      <span className="authorLibraryDocumentTitle">{document.title}</span>
    </>
  );

  // A stored file (uploaded PDF fallback) always routes through the internal
  // reader page, even when a source_url is also present — the reader shows
  // both "Open PDF" and "Open original source" so neither option is hidden.
  if (!document.stored_file_url && document.source_url) {
    return (
      <a
        className="authorLibraryDocumentRow authorLibraryDocumentLink"
        href={document.source_url}
        rel="noreferrer"
        target="_blank"
      >
        {content}
      </a>
    );
  }

  return (
    <Link className="authorLibraryDocumentRow authorLibraryDocumentLink" to={documentRoute(authorId, document.id)}>
      {content}
    </Link>
  );
}

export default function AuthorLibrary() {
  const { authorId = "", documentId = "" } = useParams<RouteParams>();
  const isGallery = !authorId;
  const isReader = Boolean(authorId && documentId);

  const [authors, setAuthors] = useState<RagLibraryAuthor[]>([]);
  const [authorsLoading, setAuthorsLoading] = useState(false);
  const [library, setLibrary] = useState<RagAuthorLibrary | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [documentDetail, setDocumentDetail] = useState<RagLibraryDocumentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openingStoredFile, setOpeningStoredFile] = useState(false);
  const [storedFileError, setStoredFileError] = useState<string | null>(null);

  async function handleOpenStoredFile(storedFileUrl: string) {
    setOpeningStoredFile(true);
    setStoredFileError(null);
    try {
      const objectUrl = await api.ragFetchSourceFileObjectUrl(storedFileUrl);
      window.open(objectUrl, "_blank", "noopener,noreferrer");
      // Give the new tab a moment to actually load the blob before revoking.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (err: unknown) {
      setStoredFileError(err instanceof Error ? err.message : String(err));
    } finally {
      setOpeningStoredFile(false);
    }
  }

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
    if (!authorId || isReader) {
      setLibrary(null);
      return;
    }
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
  }, [authorId, isReader]);

  useEffect(() => {
    if (!isReader || !documentId) {
      setDocumentDetail(null);
      return;
    }
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
  }, [documentId, isReader]);

  const groupedSections = library?.groups ?? [];
  const isDecadeGrouping = library?.grouping.primary_field === "publication_year";
  const decadeGroups = isDecadeGrouping && groupedSections.length ? groupDocumentsByDecade(groupedSections) : null;
  const authorName = library?.author.name ?? documentDetail?.author_name ?? "Author Library";
  const title = isGallery
    ? "Author Library"
    : isReader
      ? (documentDetail?.title ?? "Original source")
      : authorName;

  const totalDocuments = authors.reduce((sum, author) => sum + author.document_count, 0);
  const galleryStatPill = authors.length
    ? `${docCountLabel(totalDocuments)} · ${authors.length} author${authors.length === 1 ? "" : "s"}`
    : null;

  return (
    <PageShell
      title={title}
      subtitle={isGallery ? "Browse authors, documents, and curated passages ingested into the corpus." : undefined}
      headerActions={(
        <div className="authorLibraryHeaderActions">
          {isGallery && galleryStatPill ? <span className="researchPageMetaPill">{galleryStatPill}</span> : null}
          {!isGallery ? <Link className="btn" to="/author-library">All authors</Link> : null}
          {authorId && isReader ? (
            <Link className="btn" to={authorRoute(authorId)}>Back to library</Link>
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
                {authors.map((author) => {
                  const tag = authorTagLabel(author);
                  return (
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
                          <div className="authorLibraryGalleryMeta">
                            {tag ? <span className="authorLibraryGalleryTag">{tag}</span> : null}
                            <span className="authorLibraryGalleryDocCount">{docCountLabel(author.document_count)}</span>
                          </div>
                        </div>
                      </div>
                    </Link>
                  );
                })}
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
                        <div className="authorLibraryGalleryMeta">
                          {(() => {
                            const tag = authorTagLabel(library.author);
                            return tag ? <span className="authorLibraryGalleryTag">{tag}</span> : null;
                          })()}
                          <span className="authorLibraryGalleryDocCount">
                            {docCountLabel(library.author.document_count)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </section>

                <section className="grid authorLibraryLibraryPage">
                  <div className="card authorLibraryListPanel">
                    <div className="cardTitle">Writings</div>
                    <div className="muted">
                      Each title opens the original letter or article source. CapitalOS no longer renders ingested content inside the library.
                    </div>
                    {decadeGroups ? (
                      <div className="authorLibraryGroupStack">
                        {decadeGroups.map((group) => (
                          <section key={group.label} className="authorLibraryGroup">
                            <div className="authorLibraryGroupHeader">
                              <h3>{group.label}</h3>
                            </div>
                            <div className="authorLibraryDocumentStack">
                              {group.documents.map((document) => (
                                <DocumentLinkCard key={document.id} authorId={authorId} document={document} />
                              ))}
                            </div>
                          </section>
                        ))}
                      </div>
                    ) : groupedSections.length ? (
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
                <div className="cardTitle">Loading source</div>
                <div className="muted">Fetching the source handoff for this document...</div>
              </div>
            ) : null}

            {documentDetail ? (
              <div className="card authorLibraryReaderSurface" data-testid="author-library-source-card">
                <div className="authorLibraryReaderContent">
                  <div className="authorLibraryReaderHeader">
                    <div>
                      <div className="authorLibraryBreadcrumbs">
                        <Link to="/author-library">Authors</Link>
                        <span aria-hidden="true">/</span>
                        <Link to={authorRoute(authorId)}>{documentDetail.author_name ?? authorId}</Link>
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

                  <div className="authorLibrarySourceFallback" data-testid="author-library-source-only">
                    <div className="cardTitle">Open original source</div>
                    <div className="muted">
                      Author Library now hands this document off to its original source instead of rendering extracted content inside CapitalOS.
                    </div>
                    <div className="authorLibrarySourceLinkRow">
                      {documentDetail.stored_file_url ? (
                        <button
                          type="button"
                          className="authorLibrarySourceLinkButton"
                          disabled={openingStoredFile}
                          onClick={() => void handleOpenStoredFile(documentDetail.stored_file_url!)}
                        >
                          {openingStoredFile ? "Opening…" : "Open PDF ↗"}
                        </button>
                      ) : null}
                      {documentDetail.source_url ? (
                        <a
                          className="authorLibrarySourceLinkButton"
                          href={documentDetail.source_url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          Open original source ↗
                        </a>
                      ) : null}
                    </div>
                    {documentDetail.stored_file_url ? (
                      <div className="muted" style={{ marginTop: "8px" }}>
                        This PDF was uploaded manually because the original host blocked automatic fetching.
                        {documentDetail.source_url
                          ? " \"Open original source\" links to that host and may still fail — \"Open PDF\" opens CapitalOS's own stored copy."
                          : ""}
                      </div>
                    ) : null}
                    {!documentDetail.stored_file_url && !documentDetail.source_url ? (
                      <div className="muted">No source URL is stored for this document yet.</div>
                    ) : null}
                    {storedFileError ? <div className="error" style={{ marginTop: "8px" }}>{storedFileError}</div> : null}
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </PageShell>
  );
}
