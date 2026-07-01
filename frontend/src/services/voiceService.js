/**
 * VOICE GENERATION SERVICE (DECOUPLED)
 * ------------------------------------------------
 * This service acts as the bridge between the Next.js Frontend
 * and the Python Inference Worker (Colab/GPU).
 * 
 * CURRENT STATUS: Phase 1 (Manual Validation)
 * TODO: Phase 2 Integration - Connect via Redis/Celery
 */
const WORKER_URL = process.env.NEXT_PUBLIC_VOICE_WORKER_URL;

export const generateCharacterVoice = async (text, characterId) => {
    console.log(`[System] Preparing to send text to worker: ${text}`);

    if (!WORKER_URL) {
        console.warn("[System] Voice Worker URL not configured. Skipping generation.");
        return null;
    }

    try {
        const response = await fetch(`${WORKER_URL}/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: text,
                character_id: characterId,
                timeout: 5000
            })
        });

        if (!response.ok) throw new Error("Worker Busy");
        return await response.blob();

    } catch (error) {
        console.error("[System] Fallback to text-only mode:", error);
        return null;
    }
};