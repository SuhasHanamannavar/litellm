-- AlterTable
ALTER TABLE "LiteLLM_MCPServerTable" ADD COLUMN     "data_boundary" TEXT;

-- AlterTable
ALTER TABLE "LiteLLM_ObjectPermissionTable" ADD COLUMN     "mcp_data_boundaries" TEXT[] DEFAULT ARRAY[]::TEXT[];
