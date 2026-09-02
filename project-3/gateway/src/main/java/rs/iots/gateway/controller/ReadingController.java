package rs.iots.gateway.controller;

import io.grpc.stub.StreamObserver;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import rs.iots.datamanager.v1.*;
import rs.iots.gateway.dto.*;
import rs.iots.gateway.mapper.ReadingMapper;

import java.time.Instant;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

@RestController
@RequestMapping("/api/v1/readings")
@Tag(name = "Readings", description = "CRUD i agregacije nad očitavanjima IoT senzora")
public class ReadingController {

    private final ReadingServiceGrpc.ReadingServiceBlockingStub stub;
    private final ReadingServiceGrpc.ReadingServiceStub asyncStub;
    private final ReadingMapper mapper;

    public ReadingController(ReadingServiceGrpc.ReadingServiceBlockingStub stub,
                             ReadingServiceGrpc.ReadingServiceStub asyncStub,
                             ReadingMapper mapper) {
        this.stub = stub;
        this.asyncStub = asyncStub;
        this.mapper = mapper;
    }

    @Operation(summary = "Dodavanje novog očitavanja")
    @ApiResponse(responseCode = "201", description = "Očitavanje kreirano")
    @PostMapping
    public ResponseEntity<ReadingDto> create(@Valid @RequestBody ReadingDto body) {
        Reading created = stub.create(CreateRequest.newBuilder()
                .setReading(mapper.toProto(body)).build());
        return ResponseEntity.status(HttpStatus.CREATED).body(mapper.toDto(created));
    }

    @Operation(summary = "Grupni unos očitavanja (koristi ga SensorGenerator)")
    @PostMapping("/batch")
    public BatchResultDto createBatch(@RequestBody List<@Valid ReadingDto> body) {
        AtomicReference<BatchResponse> result = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);

        StreamObserver<Reading> request = asyncStub.batchCreate(new StreamObserver<>() {
            @Override public void onNext(BatchResponse value) { result.set(value); }
            @Override public void onError(Throwable t) { failure.set(t); done.countDown(); }
            @Override public void onCompleted() { done.countDown(); }
        });
        try {
            body.forEach(dto -> request.onNext(mapper.toProto(dto)));
            request.onCompleted();
            if (!done.await(60, TimeUnit.SECONDS)) {
                throw new IllegalStateException("DataManager batch timeout");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Prekinut grupni unos", e);
        }
        if (failure.get() != null) {
            throw new RuntimeException(failure.get());
        }
        return new BatchResultDto(result.get().getCreated());
    }

    @Operation(summary = "Dohvatanje očitavanja po identifikatoru")
    @ApiResponses({@ApiResponse(responseCode = "200", description = "OK"),
                   @ApiResponse(responseCode = "404", description = "Nije pronađeno")})
    @GetMapping("/{id}")
    public ReadingDto get(@PathVariable long id) {
        return mapper.toDto(stub.get(GetRequest.newBuilder().setId(id).build()));
    }

    @Operation(summary = "Pretraga očitavanja po uređaju i vremenskom periodu")
    @GetMapping
    public PageDto search(
            @Parameter(description = "Identifikator uređaja; izostavljeno = svi uređaji")
            @RequestParam(required = false, defaultValue = "") String deviceId,
            @Parameter(description = "Početak perioda, ISO-8601", example = "2020-07-12T00:00:00Z")
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant from,
            @Parameter(description = "Kraj perioda, ISO-8601", example = "2020-07-13T00:00:00Z")
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant to,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "50") int size) {

        ListRequest.Builder req = ListRequest.newBuilder()
                .setDeviceId(deviceId).setPage(page).setPageSize(size);
        if (from != null) req.setStartTime(ReadingMapper.toTimestamp(from));
        if (to != null) req.setEndTime(ReadingMapper.toTimestamp(to));

        ListResponse res = stub.list(req.build());
        return new PageDto(res.getReadingsList().stream().map(mapper::toDto).toList(),
                res.getTotal(), page, size);
    }

    @Operation(summary = "Ažuriranje postojećeg očitavanja")
    @PutMapping("/{id}")
    public ReadingDto update(@PathVariable long id, @Valid @RequestBody ReadingDto body) {
        Reading updated = stub.update(UpdateRequest.newBuilder()
                .setId(id).setReading(mapper.toProto(body)).build());
        return mapper.toDto(updated);
    }

    @Operation(summary = "Brisanje očitavanja")
    @ApiResponse(responseCode = "204", description = "Obrisano")
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        DeleteResponse res = stub.delete(DeleteRequest.newBuilder().setId(id).build());
        return res.getDeleted() ? ResponseEntity.noContent().build()
                                : ResponseEntity.notFound().build();
    }

    @Operation(summary = "Agregacije (min, max, avg, sum) nad poljem u vremenskom periodu")
    @GetMapping("/aggregate")
    public AggregateDto aggregate(
            @RequestParam(required = false, defaultValue = "") String deviceId,
            @Parameter(description = "temperature | humidity | co | smoke")
            @RequestParam(defaultValue = "temperature") String field,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant to) {

        AggregateRequest.Builder req = AggregateRequest.newBuilder()
                .setDeviceId(deviceId).setField(field);
        if (from != null) req.setStartTime(ReadingMapper.toTimestamp(from));
        if (to != null) req.setEndTime(ReadingMapper.toTimestamp(to));

        AggregateResponse r = stub.aggregate(req.build());
        return new AggregateDto(r.getField(), deviceId, r.getMin(), r.getMax(),
                r.getAvg(), r.getSum(), r.getCount());
    }
}
