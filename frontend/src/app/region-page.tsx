"use client";

// One parsed Document page with Regions boxed on it. The image is the page as Nemotron Parse read it, and a box is a
// fraction of that image, origin at the top left (GET /api/documents/{hash}/pages/{n}/image). Shared by the Trials
// page's Citation panel and its trial question's panel.

export type RegionBox = { span_id: string; x0: number; y0: number; x1: number; y1: number };

export function RegionPage({ documentHash, page, filename, boxes, active, onSelect }: {
  documentHash: string;
  page: number;
  filename: string;
  boxes: RegionBox[];
  active?: string | null;
  onSelect?: (spanId: string) => void;
}) {
  return (
    <figure className="flex flex-col gap-2">
      <div className="relative border border-border bg-surface">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/api/documents/${encodeURIComponent(documentHash)}/pages/${page}/image`}
             alt={`Page ${page} of ${filename}`} className="block w-full" />
        {boxes.map((box) => {
          const style = {
            left: `${box.x0 * 100}%`, top: `${box.y0 * 100}%`,
            width: `${(box.x1 - box.x0) * 100}%`, height: `${(box.y1 - box.y0) * 100}%`,
          };
          // A thin outline drawn just outside the box, so it frames the words instead of sitting on them.
          const shade = box.span_id === active ? "bg-accent/15" : "bg-accent/5";
          return onSelect ? (
            <button key={box.span_id} type="button" aria-label={`Cited region on page ${page}`}
                    onClick={() => onSelect(box.span_id)}
                    className={`absolute outline-1 outline-offset-2 outline-accent ${shade}`} style={style} />
          ) : (
            <span key={box.span_id} aria-label={`Cited region on page ${page}`} role="img"
                  className={`absolute outline-1 outline-offset-2 outline-accent ${shade}`} style={style} />
          );
        })}
      </div>
      <figcaption className="text-sm text-muted">Page {page} of {filename}</figcaption>
    </figure>
  );
}
