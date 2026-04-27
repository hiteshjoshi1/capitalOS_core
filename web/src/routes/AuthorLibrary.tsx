import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import PageShell from "../components/PageShell";
import "../App.css";
import {
  api,
  type RagAuthorLibrary,
  type RagLibraryAuthor,
  type RagLibraryDocumentDetail,
  type RagLibraryDocumentSummary,
  type RagLibraryRelatedDocument,
} from "../lib/api";

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

function prettyFieldName(field: string | null | undefined): string {
  if (!field) return "Documents";
  return field
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString();
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

function documentMetaEntries(document: RagLibraryDocumentSummary | RagLibraryDocumentDetail): Array<[string, string]> {
  const entries: Array<[string, string | null | undefined]> = [
    ["Author", document.author_name ?? document.author_id],
    ["Date", document.publication_label],
    ["Venue", document.venue],
    ["Collection", document.collection],
    ["Canonical", document.canonical_status],
    ["Source type", document.source_type],
    ["Work type", document.work_type],
  ];
  return entries.filter(([, value]) => Boolean(value)) as Array<[string, string]>;
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

function MetadataChips({ entries }: { entries: Array<[string, string]> }) {
  if (!entries.length) return null;
  return (
    <div className="authorLibraryMetaGrid">
      {entries.map(([label, value]) => (
        <span key={`${label}:${value}`} className="authorLibraryMetaChip">
          <strong>{label}:</strong> {value}
        </span>
      ))}
    </div>
  );
}

function RelatedDocumentLinks({
  label,
  authorId,
  documents,
}: {
  label: string;
  authorId: string;
  documents: RagLibraryRelatedDocument[];
}) {
  if (!documents.length) return null;
  return (
    <section className="authorLibraryRelatedGroup">
      <div className="cardTitle">{label}</div>
      <div className="authorLibraryRelatedList">
        {documents.map((document) => (
          <Link
            key={document.id}
            className="authorLibraryRelatedButton"
            to={documentRoute(authorId, document.id)}
          >
            <span className="authorLibraryRelatedTitle">{document.title}</span>
            <span className="muted">
              {[document.author_name, document.publication_label, document.work_type].filter(Boolean).join(" • ") || "Open related document"}
            </span>
          </Link>
        ))}
      </div>
    </section>
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
    <Link className="authorLibraryDocumentCard authorLibraryDocumentLink" to={documentRoute(authorId, document.id)}>
      <div className="authorLibraryDocumentHeader">
        <div>
          <div className="authorLibraryDocumentTitle">{document.title}</div>
          <div className="muted">{document.author_name ?? document.author_id ?? "Unknown author"}</div>
        </div>
        <span className="pill">{document.char_count.toLocaleString()} chars</span>
      </div>
      <MetadataChips entries={documentMetaEntries(document)} />
      <div className="authorLibraryMetaGrid">
        {document.parent_title ? (
          <span className="authorLibraryMetaChip">
            <strong>Parent:</strong> {document.parent_title}
          </span>
        ) : null}
        {document.child_count > 0 ? (
          <span className="authorLibraryMetaChip">
            <strong>Related:</strong> {document.child_count} linked
          </span>
        ) : null}
      </div>
      {document.source_url ? (
        <span className="authorLibraryMetaChip">
          <strong>Source:</strong> {document.source_url}
        </span>
      ) : null}
    </Link>
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
  const subtitle = isGallery
    ? "Browse available authors as readable corpora, then open any logical document inside a dedicated reader."
    : isReader
      ? (library?.author.about_text ?? "Read one logical document with provenance, metadata, and related works.")
      : (library?.author.about_text ?? "Browse this corpus by collection, section, work type, and date.");

  return (
    <PageShell
      title={title}
      subtitle={subtitle}
      headerActions={(
        <div className="authorLibraryHeaderActions">
          {!isGallery ? <Link className="btn" to="/author-library">All authors</Link> : null}
          {authorId && !isReader ? (
            <span className="pill">
              {library?.grouping.primary_field
                ? `Grouped by ${prettyFieldName(library.grouping.primary_field)}`
                : "Flat document list"}
            </span>
          ) : null}
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
                  <article key={author.id} className="card authorLibraryGalleryCard">
                    <div className="authorLibraryGalleryHeader">
                      <AuthorPortrait author={author} className="authorLibraryGalleryPortrait" />
                      <div className="authorLibraryGalleryIdentity">
                        <h2>{author.name}</h2>
                        <div className="muted">
                          {author.about_text ?? "Open this corpus to browse its logical documents and provenance."}
                        </div>
                      </div>
                    </div>
                    <div className="authorLibraryMetaGrid">
                      <span className="authorLibraryMetaChip">
                        <strong>Documents:</strong> {author.document_count}
                      </span>
                      <span className="authorLibraryMetaChip">
                        <strong>Sources:</strong> {author.source_count}
                      </span>
                      {author.latest_document_at ? (
                        <span className="authorLibraryMetaChip">
                          <strong>Updated:</strong> {formatDateTime(author.latest_document_at)}
                        </span>
                      ) : null}
                    </div>
                    <div className="authorLibraryMetaGrid">
                      {author.collections.map((collection) => (
                        <span key={`${author.id}:${collection}`} className="authorLibraryMetaChip">
                          <strong>Collection:</strong> {collection}
                        </span>
                      ))}
                      {author.work_types.map((workType) => (
                        <span key={`${author.id}:${workType}`} className="authorLibraryMetaChip">
                          <strong>Work type:</strong> {workType}
                        </span>
                      ))}
                    </div>
                    <Link className="btn authorLibraryBrowseLink" to={authorRoute(author.id)}>
                      Browse {author.name}'s library
                    </Link>
                  </article>
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
                  <div className="card authorLibraryAuthorCard">
                    <div className="authorLibraryGalleryHeader">
                      <AuthorPortrait author={library.author} />
                      <div className="authorLibraryGalleryIdentity">
                        <h2>{library.author.name}</h2>
                        <div className="muted">
                          {library.author.about_text ?? "Browse grouped logical documents, provenance, and related works."}
                        </div>
                      </div>
                    </div>
                    <div className="authorLibraryMetaGrid">
                      <span className="authorLibraryMetaChip">
                        <strong>Documents:</strong> {library.author.document_count}
                      </span>
                      <span className="authorLibraryMetaChip">
                        <strong>Sources:</strong> {library.author.source_count}
                      </span>
                      {library.grouping.primary_field ? (
                        <span className="authorLibraryMetaChip">
                          <strong>Primary grouping:</strong> {prettyFieldName(library.grouping.primary_field)}
                        </span>
                      ) : null}
                      {library.grouping.secondary_field ? (
                        <span className="authorLibraryMetaChip">
                          <strong>Secondary grouping:</strong> {prettyFieldName(library.grouping.secondary_field)}
                        </span>
                      ) : null}
                    </div>
                    <div className="authorLibraryMetaGrid">
                      {library.author.collections.map((collection) => (
                        <span key={`${library.author.id}:${collection}`} className="authorLibraryMetaChip">
                          <strong>Collection:</strong> {collection}
                        </span>
                      ))}
                      {library.author.work_types.map((workType) => (
                        <span key={`${library.author.id}:${workType}`} className="authorLibraryMetaChip">
                          <strong>Work type:</strong> {workType}
                        </span>
                      ))}
                      {library.author.latest_document_at ? (
                        <span className="authorLibraryMetaChip">
                          <strong>Updated:</strong> {formatDateTime(library.author.latest_document_at)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </section>

                <section className="grid authorLibraryLibraryPage">
                  <div className="card authorLibraryListPanel">
                    <div className="cardTitle">Browse logical documents</div>
                    {groupedSections.length ? (
                      <div className="authorLibraryGroupStack">
                        {groupedSections.map((group) => (
                          <section key={`${group.field}:${group.value}`} className="authorLibraryGroup">
                            <div className="authorLibraryGroupHeader">
                              <h3>{group.label}</h3>
                              <span className="pill">
                                {prettyFieldName(group.field)} • {group.document_count}
                              </span>
                            </div>
                            {group.secondary_groups.length ? (
                              <div className="authorLibrarySecondaryStack">
                                {group.secondary_groups.map((secondaryGroup) => (
                                  <div key={`${group.value}:${secondaryGroup.value}`} className="authorLibrarySecondaryGroup">
                                    <div className="cardTitle">
                                      {prettyFieldName(secondaryGroup.field)}: {secondaryGroup.label}
                                    </div>
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
                      <div className="muted">
                        {documentDetail.author_name ?? documentDetail.author_id ?? "Unknown author"}
                      </div>
                    </div>
                    <span className="pill">{documentDetail.char_count.toLocaleString()} chars</span>
                  </div>

                  <MetadataChips entries={documentMetaEntries(documentDetail)} />

                  <div className="authorLibraryMetaGrid">
                    {documentDetail.source_section ? (
                      <span className="authorLibraryMetaChip">
                        <strong>Section:</strong> {documentDetail.source_section}
                      </span>
                    ) : null}
                    {documentDetail.source_author_name ? (
                      <span className="authorLibraryMetaChip">
                        <strong>Source provenance:</strong> {documentDetail.source_author_name}
                      </span>
                    ) : null}
                    <span className="authorLibraryMetaChip">
                      <strong>Stored:</strong> {formatDateTime(documentDetail.created_at)}
                    </span>
                  </div>

                  {documentDetail.source_url ? (
                    <a className="authorLibrarySourceLink" href={documentDetail.source_url} rel="noreferrer" target="_blank">
                      Open provenance link
                    </a>
                  ) : null}

                  <RelatedDocumentLinks
                    label="Parent document"
                    authorId={authorId}
                    documents={documentDetail.parent_document ? [documentDetail.parent_document] : []}
                  />
                  <RelatedDocumentLinks
                    label="Related documents"
                    authorId={authorId}
                    documents={documentDetail.child_documents}
                  />

                  <div className="authorLibraryReaderText" data-testid="author-library-reader-text">
                    {documentDetail.clean_text}
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
