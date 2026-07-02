import { useState } from 'react';
import type { Message } from '../../types';

export function ImageMessage({ message }: { message: Message }) {
  const [loaded, setLoaded] = useState(false);
  if (!message.image_src) return null;
  return (
    <div className="my-3 max-w-lg">
      <div className="rounded-lg overflow-hidden border border-border-300/15 bg-bg-000">
        {/* Reserve vertical space until the image loads so the virtualized row
            doesn't grow from ~0 to full height on load (which jumps scroll).
            Cleared on load; followOutput re-pins any residual delta smoothly. */}
        <img
          src={message.image_src}
          alt={message.image_caption || 'Image from assistant'}
          onLoad={() => setLoaded(true)}
          className={`block w-full h-auto${loaded ? '' : ' min-h-[180px]'}`}
        />
        {message.image_caption && (
          <div className="px-3 py-2 text-sm text-text-300 border-t border-border-300/15">
            {message.image_caption}
          </div>
        )}
      </div>
    </div>
  );
}
