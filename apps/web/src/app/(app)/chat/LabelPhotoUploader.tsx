'use client';

// SP-143 — stub. Impl real vem em T-B541: abre file picker, faz upload
// via /api/media, envia POST /chat/messages com media_ids +
// promote_food_item_id, e o handler _handle_nutrition_label do backend
// acopla a promocao ao food_item.

export function LabelPhotoUploader({
  onClose,
}: {
  promoteFoodItemId: string;
  itemName: string;
  onClose: () => void;
  onSent: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm rounded bg-white p-4 text-sm dark:bg-slate-900">
        <p className="mb-3">Upload de foto do rótulo ainda não implementado (T-B541).</p>
        <button
          type="button"
          onClick={onClose}
          className="rounded bg-slate-900 px-3 py-1 text-white dark:bg-slate-100 dark:text-slate-900"
        >
          Fechar
        </button>
      </div>
    </div>
  );
}
