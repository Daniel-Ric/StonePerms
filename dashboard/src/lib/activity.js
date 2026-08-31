const PERMISSION_ACTION =
  /permission|editor|group|track|node|parent|meta|prefix|suffix|promote|demote|membership/i

export function isPermissionActivity(entry) {
  return PERMISSION_ACTION.test(String(entry?.action || ''))
}

export function buildPermissionActivity(entries, options = {}) {
  const hours = options.hours || 24
  const bucketHours = options.bucketHours || 2
  const now = Number(options.now ?? Math.floor(Date.now() / 1000))
  const bucketSeconds = bucketHours * 3600
  const bucketCount = Math.ceil(hours / bucketHours)
  const end = Math.floor(now / 3600) * 3600 + 3600
  const start = end - bucketCount * bucketSeconds
  const formatter = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  const buckets = Array.from({ length: bucketCount }, (_, index) => ({
    start: start + index * bucketSeconds,
    label: formatter.format(new Date((start + index * bucketSeconds) * 1000)),
    success: 0,
    failed: 0,
    total: 0,
  }))

  for (const entry of entries.filter(isPermissionActivity)) {
    const timestamp = Number(entry.createdAt)
    if (!Number.isFinite(timestamp) || timestamp < start || timestamp >= end) continue
    const bucket = buckets[Math.floor((timestamp - start) / bucketSeconds)]
    if (!bucket) continue
    if (entry.outcome === 'failed') bucket.failed += 1
    else bucket.success += 1
    bucket.total += 1
  }

  const total = buckets.reduce((sum, bucket) => sum + bucket.total, 0)
  const failures = buckets.reduce((sum, bucket) => sum + bucket.failed, 0)
  return {
    buckets,
    total,
    failures,
    activeBuckets: buckets.filter((bucket) => bucket.total > 0).length,
    max: Math.max(1, ...buckets.map((bucket) => bucket.total)),
  }
}
