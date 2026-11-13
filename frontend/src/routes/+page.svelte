<script lang="ts">
	import { onMount } from 'svelte';

	type Prediction = {
		is_viral: boolean;
		label: string;
		viral_probability: number;
		cached: boolean;
	};

	const DEFAULT_GENRES = [
		'Classical',
		'Country',
		'Electronic',
		'Hip-Hop',
		'Indie',
		'Jazz',
		'Latin',
		'Pop',
		'R&B',
		'Rock'
	];

	const SAMPLES: Record<string, Record<string, number | string>> = {
		'Pop banger': {
			genre: 'Pop',
			release_year: 2024,
			duration_sec: 185,
			danceability: 0.86,
			energy: 0.82,
			valence: 0.71,
			tempo_bpm: 122,
			acousticness: 0.04,
			instrumentalness: 0.0,
			speechiness: 0.06,
			liveness: 0.12,
			loudness_db: -5.2,
			streams: 42000000
		},
		'Bedroom demo': {
			genre: 'Indie',
			release_year: 2019,
			duration_sec: 240,
			danceability: 0.42,
			energy: 0.31,
			valence: 0.28,
			tempo_bpm: 92,
			acousticness: 0.74,
			instrumentalness: 0.35,
			speechiness: 0.03,
			liveness: 0.1,
			loudness_db: -14.5,
			streams: 32000
		}
	};

	const SLIDERS = [
		{ key: 'danceability', label: 'Danceability', hint: 'How suitable the track is for dancing' },
		{ key: 'energy', label: 'Energy', hint: 'Perceptual measure of intensity and activity' },
		{ key: 'valence', label: 'Valence', hint: 'Musical positivity — happy vs. melancholic' },
		{ key: 'acousticness', label: 'Acousticness', hint: 'Likelihood the track is acoustic' },
		{ key: 'instrumentalness', label: 'Instrumentalness', hint: 'Chance the track has no vocals' },
		{ key: 'speechiness', label: 'Speechiness', hint: 'Presence of spoken words' },
		{ key: 'liveness', label: 'Liveness', hint: 'Detected presence of an audience' }
	] as const;

	let genres = $state(DEFAULT_GENRES);
	let form = $state({
		genre: 'Pop',
		release_year: 2024,
		duration_sec: 195,
		danceability: 0.75,
		energy: 0.7,
		valence: 0.6,
		tempo_bpm: 120,
		acousticness: 0.2,
		instrumentalness: 0.05,
		speechiness: 0.08,
		liveness: 0.15,
		loudness_db: -7,
		streams: 5000000
	});
	let loading = $state(false);
	let error = $state<string | null>(null);
	let result = $state<Prediction | null>(null);
	let lastPayload = $state<string>('');

	const probabilityPct = $derived(
		result ? Math.round(result.viral_probability * 1000) / 10 : 0
	);
	const ringStyle = $derived(
		`background: conic-gradient(var(--color-matte-400) ${probabilityPct * 3.6}deg, var(--color-line) 0deg)`
	);

	onMount(async () => {
		try {
			const res = await fetch('/api/genres');
			if (res.ok) {
				const data = await res.json();
				if (Array.isArray(data) && data.length > 0) genres = data;
			}
		} catch {
			// backend offline — fall back to the static genre list
		}
	});

	function loadSample(name: string) {
		const sample = SAMPLES[name];
		if (!sample) return;
		form = { ...form, ...(sample as Partial<typeof form>) };
		result = null;
		error = null;
	}

	async function submit() {
		loading = true;
		error = null;
		result = null;
		const payload = JSON.stringify(form);
		lastPayload = payload;
		try {
			const res = await fetch('/api/predict', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: payload
			});
			const data = await res.json();
			if (!res.ok) {
				throw new Error(
					typeof data?.detail === 'string'
						? data.detail
						: 'The request was rejected. Check your input values.'
				);
			}
			result = data as Prediction;
		} catch (e) {
			error =
				e instanceof Error && e.message !== 'Failed to fetch'
					? e.message
					: 'Could not reach the prediction API. Is the backend running on port 8080?';
		} finally {
			loading = false;
		}
	}

	function reset() {
		form = {
			genre: 'Pop',
			release_year: 2024,
			duration_sec: 195,
			danceability: 0.75,
			energy: 0.7,
			valence: 0.6,
			tempo_bpm: 120,
			acousticness: 0.2,
			instrumentalness: 0.05,
			speechiness: 0.08,
			liveness: 0.15,
			loudness_db: -7,
			streams: 5000000
		};
		result = null;
		error = null;
	}
</script>

<svelte:head>
	<title>Virality Predictor — Spotify Song Virality</title>
</svelte:head>

<div class="mx-auto min-h-screen max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
	<header class="mb-10 flex flex-wrap items-end justify-between gap-4">
		<div>
			<p class="mb-2 text-xs font-semibold tracking-[0.3em] text-matte-400">
				Spotify Song Virality
			</p>
			<h1 class="text-3xl font-bold tracking-tight text-matte-300 sm:text-4xl">
				Will this song go viral ?
			</h1>
			<p class="mt-2 max-w-xl text-sm text-muted">
				Describe a track's audio features and streaming stats. A logistic regression
				model trained on 10,000 tracks will predict its viral potential.
			</p>
		</div>
		<div
			class="flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 text-xs text-muted"
		>
			<span class="h-1.5 w-1.5 rounded-full bg-matte-400"></span>
			GET /api/predict · port 8080
		</div>
	</header>

	<div class="grid gap-6 lg:grid-cols-5">
		<section
			class="rounded-2xl border border-line bg-panel/80 p-6 shadow-[0_20px_60px_-30px_rgb(0_0_0_0.9)] backdrop-blur lg:col-span-3"
		>
			<div class="mb-5 flex items-center justify-between">
				<h2 class="text-sm font-semibold tracking-wide text-matte-200 uppercase">
					Track profile
				</h2>
				<div class="flex gap-2">
					{#each Object.keys(SAMPLES) as name}
						<button
							type="button"
							onclick={() => loadSample(name)}
							class="rounded-lg border border-line bg-panel-2 px-2.5 py-1 text-xs text-matte-300 transition hover:border-matte-600 hover:text-matte-100"
						>
							{name.trim()}
						</button>
					{/each}
					<button
						type="button"
						onclick={reset}
						class="rounded-lg border border-line bg-panel-2 px-2.5 py-1 text-xs text-muted transition hover:border-matte-600 hover:text-matte-100"
					>
						Reset
					</button>
				</div>
			</div>

			<form
				class="space-y-6"
				onsubmit={(e) => {
					e.preventDefault();
					submit();
				}}
			>
				<div class="grid gap-4 sm:grid-cols-2">
					<label class="block">
						<span class="mb-1.5 block text-xs font-medium text-matte-300">Genre</span>
						<select
							bind:value={form.genre}
							class="w-full appearance-none rounded-lg border border-line bg-panel-2 px-3 py-2.5 pr-9 text-sm text-matte-100 outline-none transition focus:border-matte-500 focus:ring-2 focus:ring-matte-700"
						>
							{#each genres as genre}
								<option value={genre}>{genre}</option>
							{/each}
						</select>
					</label>

					<label class="block">
						<span class="mb-1.5 block text-xs font-medium text-matte-300">Streams</span>
						<input
							type="number"
							min="0"
							bind:value={form.streams}
							class="w-full rounded-lg border border-line bg-panel-2 px-3 py-2.5 text-sm text-matte-100 outline-none transition focus:border-matte-500 focus:ring-2 focus:ring-matte-700"
						/>
					</label>

					<label class="block">
						<span class="mb-1.5 block text-xs font-medium text-matte-300">Release year</span>
						<input
							type="number"
							min="2010"
							max="2025"
							bind:value={form.release_year}
							class="w-full rounded-lg border border-line bg-panel-2 px-3 py-2.5 text-sm text-matte-100 outline-none transition focus:border-matte-500 focus:ring-2 focus:ring-matte-700"
						/>
					</label>

					<label class="block">
						<span class="mb-1.5 block text-xs font-medium text-matte-300"
							>Duration (sec)</span
						>
						<input
							type="number"
							min="1"
							bind:value={form.duration_sec}
							class="w-full rounded-lg border border-line bg-panel-2 px-3 py-2.5 text-sm text-matte-100 outline-none transition focus:border-matte-500 focus:ring-2 focus:ring-matte-700"
						/>
					</label>

					<label class="block">
						<span class="mb-1.5 block text-xs font-medium text-matte-300">Tempo (BPM)</span>
						<input
							type="number"
							min="1"
							bind:value={form.tempo_bpm}
							class="w-full rounded-lg border border-line bg-panel-2 px-3 py-2.5 text-sm text-matte-100 outline-none transition focus:border-matte-500 focus:ring-2 focus:ring-matte-700"
						/>
					</label>

					<label class="block">
						<span class="mb-1.5 block text-xs font-medium text-matte-300"
							>Loudness (dB)</span
						>
						<input
							type="number"
							max="0"
							step="0.1"
							bind:value={form.loudness_db}
							class="w-full rounded-lg border border-line bg-panel-2 px-3 py-2.5 text-sm text-matte-100 outline-none transition focus:border-matte-500 focus:ring-2 focus:ring-matte-700"
						/>
					</label>
				</div>

				<div>
					<h3 class="mb-4 text-sm font-semibold tracking-wide text-matte-200 uppercase">
						Audio features
					</h3>
					<div class="grid gap-5 sm:grid-cols-2">
						{#each SLIDERS as slider}
							<label class="block">
								<span class="mb-1.5 flex items-baseline justify-between">
									<span class="text-xs font-medium text-matte-300">{slider.label}</span>
									<span class="font-mono text-xs text-matte-400">
										{Number(form[slider.key]).toFixed(2)}
									</span>
								</span>
								<input
									type="range"
									min="0"
									max="1"
									step="0.01"
									bind:value={form[slider.key]}
								/>
								<span class="mt-1 block text-[11px] text-muted/70">{slider.hint}</span>
							</label>
						{/each}
					</div>
				</div>

				<div class="flex items-center gap-3 pt-2">
					<button
						type="submit"
						disabled={loading}
						class="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-matte-600 px-4 py-3 text-sm font-semibold text-matte-50 shadow-[0_10px_30px_-10px_rgb(76_109_141_0.8)] transition hover:bg-matte-500 focus:ring-2 focus:ring-matte-400 focus:ring-offset-2 focus:ring-offset-panel focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none sm:px-8"
					>
						{#if loading}
							<span
								class="h-4 w-4 animate-spin rounded-full border-2 border-matte-200 border-t-transparent"
							></span>
							Analyzing…
						{:else}
							Predict virality
						{/if}
					</button>
					<p class="text-xs text-muted">Model: logistic regression · 13 features</p>
				</div>
			</form>
		</section>

		<aside class="lg:col-span-2">
			<div class="sticky top-6 space-y-4">
				{#if error}
					<div
						class="rounded-2xl border border-red-900/60 bg-red-950/30 p-6 text-sm text-red-300"
					>
						<p class="mb-1 font-semibold">Prediction failed</p>
						<p class="text-red-300/80">{error}</p>
					</div>
				{/if}

				{#if result}
					<div
						class="rounded-2xl border border-line bg-panel/80 p-6 shadow-[0_20px_60px_-30px_rgb(0_0_0_0.9)] backdrop-blur"
					>
						<p class="mb-4 flex items-center justify-between text-xs font-semibold tracking-[0.25em] text-matte-400 uppercase">
							Verdict
							{#if result.cached}
								<span
									class="rounded-full border border-matte-700 bg-matte-900/60 px-2 py-0.5 text-[10px] font-medium tracking-normal text-matte-300 normal-case"
								>
									served from cache
								</span>
							{/if}
						</p>

						<div class="flex items-center gap-5">
							<div
								class="grid h-24 w-24 shrink-0 place-items-center rounded-full"
								style={ringStyle}
							>
								<div
									class="grid h-[76px] w-[76px] place-items-center rounded-full bg-panel"
								>
									<div class="text-center">
										<p class="text-lg font-bold text-matte-50">{probabilityPct}%</p>
										<p class="text-[10px] tracking-wide text-muted uppercase">viral</p>
									</div>
								</div>
							</div>

							<div>
								<p
									class="text-2xl font-bold tracking-tight {result.is_viral
										? 'text-matte-200'
										: 'text-matte-400'}"
								>
									{result.label.toUpperCase()}
								</p>
								<p class="mt-1 text-sm text-muted">
									{result.is_viral
										? 'The model sees strong viral signals in this profile.'
										: 'The model reads this profile as unlikely to go viral.'}
								</p>
							</div>
						</div>

						<div class="mt-6">
							<div class="mb-1.5 flex justify-between text-[11px] text-muted">
								<span>Non-viral</span>
								<span>Viral</span>
							</div>
							<div class="h-2 w-full overflow-hidden rounded-full bg-line">
								<div
									class="h-full rounded-full bg-gradient-to-r from-matte-700 via-matte-500 to-matte-300 transition-all duration-500"
									style="width: {probabilityPct}%"
								></div>
							</div>
						</div>

						<dl class="mt-6 grid grid-cols-2 gap-3 text-xs">
							<div class="rounded-lg border border-line bg-panel-2 px-3 py-2">
								<dt class="text-muted">Genre</dt>
								<dd class="mt-0.5 font-medium text-matte-200">{form.genre}</dd>
							</div>
							<div class="rounded-lg border border-line bg-panel-2 px-3 py-2">
								<dt class="text-muted">Streams</dt>
								<dd class="mt-0.5 font-medium text-matte-200">
									{Number(form.streams).toLocaleString()}
								</dd>
							</div>
							<div class="rounded-lg border border-line bg-panel-2 px-3 py-2">
								<dt class="text-muted">Tempo</dt>
								<dd class="mt-0.5 font-medium text-matte-200">{form.tempo_bpm} BPM</dd>
							</div>
							<div class="rounded-lg border border-line bg-panel-2 px-3 py-2">
								<dt class="text-muted">Loudness</dt>
								<dd class="mt-0.5 font-medium text-matte-200">{form.loudness_db} dB</dd>
							</div>
						</dl>
					</div>
				{:else if !error}
					<div
						class="rounded-2xl border border-dashed border-line bg-panel/50 p-8 text-center backdrop-blur"
					>
						<div
							class="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl border border-line bg-panel-2"
						>
							<svg
								class="h-5 w-5 text-matte-400"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M9 19V6l12-3v13M9 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm12-3a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
								/>
							</svg>
						</div>
						<p class="text-sm font-medium text-matte-300">No prediction yet</p>
						<p class="mt-1 text-xs text-muted">
							Fill in the track profile and hit “Predict virality” to see the verdict
							here.
						</p>
					</div>
				{/if}

				{#if lastPayload && result}
					<details
						class="rounded-2xl border border-line bg-panel/60 p-4 text-xs text-muted backdrop-blur"
					>
						<summary class="cursor-pointer select-none text-matte-400">Request payload</summary>
						<pre class="mt-3 overflow-x-auto text-[11px] leading-relaxed">{lastPayload}</pre>
					</details>
				{/if}
			</div>
		</aside>
	</div>
</div>
