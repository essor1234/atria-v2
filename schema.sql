-- Atria PostgreSQL schema (REFERENCE SNAPSHOT — NOT THE SOURCE OF TRUTH).
-- The application now creates the schema from SQLAlchemy ORM models in
-- atria/db/models.py via Base.metadata.create_all(). This file is kept as a
-- human-readable reference for the column layout and may drift over time.

DROP TABLE IF EXISTS "artifacts";
DROP TABLE IF EXISTS "messages";
DROP TABLE IF EXISTS "conversations";
DROP TABLE IF EXISTS "projects";
DROP TABLE IF EXISTS "users";
DROP TABLE IF EXISTS "domains";

DROP SEQUENCE IF EXISTS "public".artifacts_id_seq;

DROP SEQUENCE IF EXISTS "public".messages_id_seq;
DROP SEQUENCE IF EXISTS "public".conversations_id_seq;
DROP SEQUENCE IF EXISTS "public".projects_id_seq;
DROP SEQUENCE IF EXISTS "public".users_id_seq;
DROP SEQUENCE IF EXISTS "public".domains_id_seq;

-- domains (referenced by projects FK, minimal stub)
CREATE SEQUENCE "public".domains_id_seq INCREMENT 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1;
CREATE TABLE "public"."domains" (
    "id" integer DEFAULT nextval('domains_id_seq') NOT NULL,
    CONSTRAINT "domains_pkey" PRIMARY KEY ("id")
);

-- users
CREATE SEQUENCE "public".users_id_seq INCREMENT 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1;
CREATE TABLE "public"."users" (
    "id" integer DEFAULT nextval('users_id_seq') NOT NULL,
    "is_deleted" boolean NOT NULL,
    "created_at" timestamp DEFAULT now() NOT NULL,
    "updated_at" timestamp,
    "email" character varying(255) NOT NULL,
    "password_hash" character varying(255),
    "display_name" character varying(100),
    "avatar_url" text,
    "role" character varying(10) NOT NULL,
    "failed_login_attempts" integer NOT NULL,
    "locked_until" timestamptz,
    "is_active" boolean NOT NULL,
    "email_verified" boolean NOT NULL,
    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX users_email_key ON public.users USING btree (email);

-- projects
CREATE SEQUENCE "public".projects_id_seq INCREMENT 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1;
CREATE TABLE "public"."projects" (
    "id" integer DEFAULT nextval('projects_id_seq') NOT NULL,
    "is_deleted" boolean NOT NULL,
    "created_at" timestamp DEFAULT now() NOT NULL,
    "updated_at" timestamp,
    "user_id" integer NOT NULL,
    "title" character varying(255) NOT NULL,
    "pinned" boolean NOT NULL,
    "domain_id" integer,
    "workspace_path" text,
    CONSTRAINT "projects_pkey" PRIMARY KEY ("id")
);

-- conversations
CREATE SEQUENCE "public".conversations_id_seq INCREMENT 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1;
CREATE TABLE "public"."conversations" (
    "id" integer DEFAULT nextval('conversations_id_seq') NOT NULL,
    "is_deleted" boolean NOT NULL,
    "created_at" timestamp DEFAULT now() NOT NULL,
    "updated_at" timestamp,
    "project_id" integer,
    "user_id" integer,
    "title" character varying(255),
    "mode" character varying(10) NOT NULL,
    "status" character varying(10) NOT NULL,
    "working_directory" text,
    CONSTRAINT "conversations_pkey" PRIMARY KEY ("id")
);

-- messages
CREATE SEQUENCE "public".messages_id_seq INCREMENT 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1;
CREATE TABLE "public"."messages" (
    "id" integer DEFAULT nextval('messages_id_seq') NOT NULL,
    "is_deleted" boolean NOT NULL,
    "created_at" timestamp DEFAULT now() NOT NULL,
    "updated_at" timestamp,
    "conversation_id" integer NOT NULL,
    "role" character varying(10) NOT NULL,
    "mode" character varying(10) NOT NULL,
    "blocks" json NOT NULL,
    CONSTRAINT "messages_pkey" PRIMARY KEY ("id")
);

-- artifacts
CREATE SEQUENCE "public".artifacts_id_seq INCREMENT 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1;
CREATE TABLE "public"."artifacts" (
    "id" integer DEFAULT nextval('artifacts_id_seq') NOT NULL,
    "is_deleted" boolean NOT NULL,
    "created_at" timestamp DEFAULT now() NOT NULL,
    "updated_at" timestamp,
    "project_id" integer,
    "conversation_id" integer,
    "type" character varying(20) NOT NULL,
    "source_mode" character varying(10),
    "title" character varying(255),
    "pinned" boolean NOT NULL,
    "payload_ref" text,
    "preview" json,
    "scope" character varying(20),
    "local_path" character varying(512),
    CONSTRAINT "artifacts_pkey" PRIMARY KEY ("id")
);
CREATE INDEX artifacts_conversation_id_idx ON public.artifacts(conversation_id) WHERE is_deleted = false;
CREATE INDEX artifacts_project_id_idx ON public.artifacts(project_id) WHERE is_deleted = false;

CREATE SEQUENCE IF NOT EXISTS pending_reviews_id_seq;
CREATE TABLE "public"."pending_reviews" (
    "id" integer DEFAULT nextval('pending_reviews_id_seq') NOT NULL,
    "created_at" timestamp DEFAULT now() NOT NULL,
    "resolved_at" timestamp,
    "request_id" character varying(64) NOT NULL,
    "kind" character varying(32) NOT NULL,
    "session_id" character varying(64),
    "user_id" integer,
    "request_data" json,
    "resolved" boolean NOT NULL DEFAULT false,
    "response_data" json,
    CONSTRAINT "pending_reviews_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "pending_reviews_request_id_key" UNIQUE ("request_id")
);
CREATE INDEX pending_reviews_session_id_idx ON public.pending_reviews(session_id);
CREATE INDEX pending_reviews_unresolved_idx ON public.pending_reviews(kind, created_at) WHERE resolved = false;

-- Foreign keys
ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_project_id_fkey" FOREIGN KEY (project_id) REFERENCES projects(id);
ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_conversation_id_fkey" FOREIGN KEY (conversation_id) REFERENCES conversations(id);
ALTER TABLE ONLY "public"."projects"
    ADD CONSTRAINT "projects_domain_id_fkey" FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE SET NULL;
ALTER TABLE ONLY "public"."projects"
    ADD CONSTRAINT "projects_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE ONLY "public"."artifacts"
    ADD CONSTRAINT "artifacts_project_id_fkey" FOREIGN KEY (project_id) REFERENCES projects(id);
ALTER TABLE ONLY "public"."artifacts"
    ADD CONSTRAINT "artifacts_conversation_id_fkey" FOREIGN KEY (conversation_id) REFERENCES conversations(id);
ALTER TABLE ONLY "public"."pending_reviews"
    ADD CONSTRAINT "pending_reviews_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
