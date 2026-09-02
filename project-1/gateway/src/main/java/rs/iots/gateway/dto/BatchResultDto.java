package rs.iots.gateway.dto;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Rezultat grupnog unosa")
public record BatchResultDto(@Schema(example = "500") long created) {}
