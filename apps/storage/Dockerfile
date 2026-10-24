FROM mcr.microsoft.com/dotnet/sdk:10.0.402 AS build
WORKDIR /src
COPY backend/Storage.csproj backend/packages.lock.json backend/
ENV DOTNET_PROCESSOR_COUNT=2 DOTNET_GCHeapHardLimit=0x20000000
RUN dotnet restore backend/Storage.csproj --locked-mode
COPY backend/ backend/
RUN dotnet publish backend/Storage.csproj -c Release --no-restore -o /out
FROM mcr.microsoft.com/dotnet/aspnet:10.0.13
WORKDIR /app
COPY --from=build /out .
ENV ASPNETCORE_URLS=http://+:8000 SIMULATOR=storage ROLE=api DOTNET_PROCESSOR_COUNT=2 DOTNET_GCHeapHardLimit=0x18000000
EXPOSE 8000
USER $APP_UID
ENTRYPOINT ["dotnet","Storage.dll"]
