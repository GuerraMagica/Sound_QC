"""Presentation of resolved policy data; no measurement comparisons."""


def specification_rows(config):
    rate, bits, loudness, peak = (config[k] for k in ("sample_rate", "bit_depth", "loudness", "true_peak"))
    if not loudness["enabled"]:
        level = "Desactivado"
    elif loudness["target_lufs"] is None:
        level = "Solo informe (sin objetivo)"
    else:
        level = f"{loudness['target_lufs']:g} LUFS ± {loudness['tolerance']:g} LU"
    loss = config.get("signal_loss", {})
    return [
        ("Sample Rate", f"Requerido: {rate['required']} Hz" if rate["required"] is not None else "Sin requisito"),
        ("Bit Depth", f"Requerido: {bits['required'] if bits['required'] is not None else 'ninguno'}; preferido: {bits['preferred'] if bits['preferred'] is not None else 'ninguno'}"),
        ("Loudness integrado", level),
        ("True Peak", f"Máximo: {peak['maximum']:g} dBTP" if peak["maximum"] is not None else "Solo informe (sin máximo)" + ("; medición desactivada con Loudness" if not loudness["enabled"] else "")),
        ("BWF / BEXT", "Requerido" if config["bwf"]["required"] else "WARNING si falta" if config["bwf"]["warn_if_missing"] else "Ignorado"),
        ("Canales físicos", ", ".join(map(str, config["channels"]["allowed"])) if config["channels"]["allowed"] is not None else "Sin restricción"),
        ("Signal loss / MOS", (f"Digital zero ≥ {loss['min_duration_ms']:g} ms; no maximum duration; "
                               f"internal: {'FAIL' if loss['fail_internal'] else 'WARNING'}; "
                               f"whole file/channel: {'FAIL' if loss['fail_total'] else 'WARNING'} (any duration); edges: INFO; "
                               f"detail limit: {loss['max_events']} critical issues; scan continues")
                              if loss.get('enabled') else "Disabled / not configured"),
        ("Clipping", f"{'FAIL' if config['clipping']['fail'] else 'WARNING'}; criterio existente: {config['clipping']['consecutive_samples']} muestras consecutivas al mismo límite, o sobrecarga digital"),
    ]
